"""Reglas de las políticas del catálogo como funciones puras.

Cada política es una función `(transacción, perfil, historial) -> señal | nada`.
Se implementan a propósito **separadas** de `scripts/build_ground_truth.py`:
el harness debe medir la calidad del sistema, no validar el sistema contra sí
mismo (D1 del diseño). Solo la precedencia y los factores de moneda se comparten
(`domain/constants.py`).

El contrato del nodo: una política devuelve una `WorkingSignal`-like
(`(code, description, severity, emitted_by)`), pero acá se devuelve un objeto
ligero propio para no acoplar el dominio al estado del grafo. El nodo convierte.
"""

from datetime import timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from src.domain.constants import BLACKLISTED_MERCHANTS, CURRENCY_FACTOR
from src.enums import Severity

# Umbrales de las políticas, en moneda de referencia (USD). Decimal para no
# mezclar tipos con los montos (`amount` es `Money` = `Decimal`).
MICRO_CHARGE_USD = Decimal("1.0")      # techo del "cobro de centavos" de FP-04
FP07_THRESHOLD_USD = Decimal("135.0")  # los "500 soles" de FP-07
FP01_MULTIPLIER = Decimal("3.0")       # "3x el promedio" de FP-01
FP06_MULTIPLIER = Decimal("2.0")       # "duplica su promedio" de FP-06
FP08_MULTIPLIER = Decimal("5.0")       # "5x el promedio del segmento" de FP-08
FP03_MAX_COUNT = 3           # "más de 3 transacciones" de FP-03
FP03_WINDOW = timedelta(minutes=5)
FP04_WINDOW = timedelta(minutes=10)
FP05_WINDOW = timedelta(hours=2)
FP09_WINDOW = timedelta(minutes=30)


class PolicySignal:
    """Señal en vuelo emitida por una política.

    No cruza al estado del grafo tal cual: `WorkingSignal` vive en `graph/state`
    y lleva `emitted_by`. El nodo que evalua convierte esto a `WorkingSignal`.
    """

    __slots__ = ("code", "description", "severity")

    def __init__(self, code: str, description: str, severity: Severity) -> None:
        self.code = code
        self.description = description
        self.severity = severity


# Código de señal → política del catálogo. Lo consume el harness para atribuir
# señales a políticas (precisión/recall por política, entregable 7).
SIGNAL_TO_POLICY = {
    "AMOUNT_OUT_OF_RANGE": "FP-01",
    "FOREIGN_NEW_DEVICE": "FP-02",
    "DEVICE_VELOCITY": "FP-03",
    "CARD_TESTING": "FP-04",
    "IMPOSSIBLE_GEO": "FP-05",
    "NEW_CHANNEL_HIGH_AMOUNT": "FP-06",
    "BLACKLISTED_MERCHANT": "FP-07",
    "NEW_ACCOUNT_HIGH_AMOUNT": "FP-08",
    "PROFILE_CHANGE_IMMEDIATE_TX": "FP-09",
    "SMURFING": "FP-11",
}


def _en_ventana(hora: int, inicio: int, fin: int) -> bool:
    """Ventana `[start, end]` **inclusive**, con cruce de medianoche soportado.

    Un cliente nocturno (`22-06`) es válido: `start > end` no está prohibido, y
    la comparación debe contemplar el cruce (contrato §2.5).
    """
    if inicio <= fin:
        return inicio <= hora <= fin
    return hora >= inicio or hora <= fin


def _lista(celda) -> list[str]:
    return [x for x in celda.split(";") if x]


# --- FP-07: comercio en lista negra sobre el umbral --------------------------


def fp07(tx, merchant_id: str, currency: str) -> PolicySignal | None:
    """FP-07: comercio en lista negra con monto sobre el umbral (en USD).

    El umbral se expresa en moneda de referencia y se convierte a la moneda de
    la cuenta (repaso 04 §3.7: los umbrales monetarios usan el mismo factor).
    """
    if merchant_id not in BLACKLISTED_MERCHANTS:
        return None
    umbral = FP07_THRESHOLD_USD * _factor(currency)
    if tx.amount <= umbral:
        return None
    return PolicySignal(
        code="BLACKLISTED_MERCHANT",
        description=f"comercio en lista negra con monto {tx.amount} > {umbral}",
        severity=Severity.HIGH,
    )


def _factor(currency: str) -> Decimal:
    """Cuánto vale 1 USD en la moneda de la cuenta."""
    return CURRENCY_FACTOR.get(currency, Decimal("1.0"))


# --- FP-01: monto > 3x y fuera de la ventana horaria -------------------------


def fp01(tx, perfil) -> PolicySignal | None:
    if tx.amount <= FP01_MULTIPLIER * perfil.usual_amount_avg:
        return None
    zona = ZoneInfo(perfil.timezone)
    local = tx.timestamp.astimezone(zona)
    if _en_ventana(local.hour, perfil.usual_hour_start, perfil.usual_hour_end):
        return None
    return PolicySignal(
        code="AMOUNT_OUT_OF_RANGE",
        description=f"monto {tx.amount} > {FP01_MULTIPLIER}x promedio y horario fuera de rango",
        severity=Severity.MEDIUM,
    )


# --- FP-02: internacional + dispositivo nuevo -------------------------------


def fp02(tx, perfil) -> PolicySignal | None:
    habituales_pais = perfil.usual_countries
    habituales_disp = perfil.usual_devices
    # Una lista vacía significa que nada está registrado como habitual, así que
    # todo es nuevo (contrato §2.5).
    pais_ajeno = tx.country not in habituales_pais
    disp_nuevo = tx.device_id not in habituales_disp
    if not (pais_ajeno and disp_nuevo):
        return None
    return PolicySignal(
        code="FOREIGN_NEW_DEVICE",
        description=f"país {tx.country} ajeno y dispositivo {tx.device_id} nuevo",
        severity=Severity.HIGH,
    )


# --- FP-03: más de 3 transacciones del mismo dispositivo en < 5 min ----------


def fp03(tx, previas) -> PolicySignal | None:
    """`previas`: historial del dispositivo (cruzando cuentas), en orden."""
    ventana = [
        f for f in previas
        if f.device_id == tx.device_id
        and tx.timestamp - f.timestamp < FP03_WINDOW
    ]
    if len(ventana) + 1 <= FP03_MAX_COUNT:
        return None
    return PolicySignal(
        code="DEVICE_VELOCITY",
        description=f"{len(ventana) + 1} transacciones del dispositivo en < 5 min",
        severity=Severity.HIGH,
    )


# --- FP-04: 2+ cobros de centavos y luego uno grande, en < 10 min ------------


def fp04(tx, perfil, previas) -> PolicySignal | None:
    factor = _factor(perfil.currency)
    techo_micro = MICRO_CHARGE_USD * factor
    micro = [
        f for f in previas
        if Decimal(f.amount) <= techo_micro
        and tx.timestamp - f.timestamp < FP04_WINDOW
    ]
    if len(micro) < 2 or tx.amount <= 2 * perfil.usual_amount_avg:
        return None
    return PolicySignal(
        code="CARD_TESTING",
        description=f"{len(micro)} cobros de centavos y luego monto {tx.amount}",
        severity=Severity.HIGH,
    )


# --- FP-05: dos países incompatibles en menos de 2 h -------------------------


def fp05(tx, previas) -> PolicySignal | None:
    lejos = [
        f for f in previas
        if f.country != tx.country
        and tx.timestamp - f.timestamp < FP05_WINDOW
    ]
    if not lejos:
        return None
    return PolicySignal(
        code="IMPOSSIBLE_GEO",
        description=f"{tx.country} tras {lejos[-1].country} en < 2 h",
        severity=Severity.HIGH,
    )


# --- FP-06: canal distinto del habitual y monto > 2x -------------------------


def fp06(tx, perfil) -> PolicySignal | None:
    if tx.channel == perfil.usual_channel or tx.amount <= FP06_MULTIPLIER * perfil.usual_amount_avg:
        return None
    return PolicySignal(
        code="NEW_CHANNEL_HIGH_AMOUNT",
        description=f"canal {tx.channel.value} nuevo y monto > {FP06_MULTIPLIER}x promedio",
        severity=Severity.MEDIUM,
    )


# --- FP-08: cuenta de menos de 30 días y monto > 5x del segmento -------------


def fp08(tx, perfil, seg_avg_usd: dict) -> PolicySignal | None:
    edad = (tx.timestamp.date() - perfil.account_creation_date).days
    if edad >= 30:
        return None
    umbral_segmento = Decimal(str(seg_avg_usd.get(perfil.segment, "0.0"))) * _factor(perfil.currency)
    if tx.amount <= FP08_MULTIPLIER * umbral_segmento:
        return None
    return PolicySignal(
        code="NEW_ACCOUNT_HIGH_AMOUNT",
        description=f"cuenta de {edad} días y monto > {FP08_MULTIPLIER}x del segmento",
        severity=Severity.HIGH,
    )


# --- FP-09: transacción dentro de los 30 min de un cambio de perfil ----------


def fp09(tx, perfil) -> PolicySignal | None:
    cambio = perfil.last_profile_update
    if not (timedelta(0) <= tx.timestamp - cambio <= FP09_WINDOW):
        return None
    return PolicySignal(
        code="PROFILE_CHANGE_IMMEDIATE_TX",
        description="transacción dentro de los 30 min de un cambio de perfil",
        severity=Severity.HIGH,
    )


# --- FP-11: 3+ pagos al mismo comercio el mismo día sobre el límite ----------


def fp11(tx, perfil, previas) -> PolicySignal | None:
    zona = ZoneInfo(perfil.timezone)
    local = tx.timestamp.astimezone(zona)
    mismo_dia = [
        f for f in previas
        if f.merchant_id == tx.merchant_id
        and f.timestamp.astimezone(zona).date() == local.date()
    ]
    if len(mismo_dia) + 1 < 3:
        return None
    suma = sum(Decimal(f.amount) for f in mismo_dia) + Decimal(tx.amount)
    if suma <= Decimal(perfil.daily_limit):
        return None
    return PolicySignal(
        code="SMURFING",
        description=f"{len(mismo_dia) + 1} pagos al mismo comercio el mismo día, suma {suma} > límite",
        severity=Severity.HIGH,
    )


# --- Dispatcher ---------------------------------------------------------------


def evaluate_for_transaction(tx, perfil, *, previas_device, previas_customer, seg_avg_usd) -> list[PolicySignal]:
    """Evalúa las políticas de un caso y devuelve sus señales.

    FP-07 queda **fuera** de acá a propósito: es la única política asignada al
    Transaction Context Agent (D2), que la emite por separado. Acá se evalúan
    las que exigen perfil e historial.

    `perfil=None` (cliente sin perfil) no permite ninguna de estas: se devuelve
    lista vacía y el nodo emite `NO_CUSTOMER_PROFILE` (repaso 04, FP-01…FP-11).
    """
    if perfil is None:
        return []

    senales: list[PolicySignal] = []

    # Perfil (sin historial)
    for fn, args in (
        (fp01, (tx, perfil)),
        (fp02, (tx, perfil)),
        (fp06, (tx, perfil)),
        (fp09, (tx, perfil)),
    ):
        senal = fn(*args)
        if senal:
            senales.append(senal)

    # Historial del dispositivo
    senal = fp03(tx, previas_device)
    if senal:
        senales.append(senal)

    # Historial del cliente
    for fn, args in (
        (fp04, (tx, perfil, previas_customer)),
        (fp05, (tx, previas_customer)),
        (fp11, (tx, perfil, previas_customer)),
    ):
        senal = fn(*args)
        if senal:
            senales.append(senal)

    # Segmento (perfil + historial agregado del dataset)
    senal = fp08(tx, perfil, seg_avg_usd)
    if senal:
        senales.append(senal)

    return senales
