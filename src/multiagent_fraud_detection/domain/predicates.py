"""Los catorce predicados del motor determinístico.

**Esto es lo único de la capa de reglas que vive en código.** Una política no está
acá: está en `data/policies/policy_bindings_*.json`, y es una conjunción de estos
predicados con parámetros (ADR-0007). Agregar una política de forma conocida no
toca este archivo; agregar una *forma* nueva sí, y por eso la biblioteca crece
sólo con un despliegue.

Tres propiedades que definen la capa:

**Sin I/O.** Ningún predicado abre una conexión ni consulta nada. El historial
llega ya cargado en el contexto, acotado por la ventana más ancha del catálogo.
Es lo que permite correr los catorce sobre las 7 000 transacciones del dataset en
segundos, sin base y sin red.

**Cada predicado declara sus insumos como dato.** De ahí salen tres cosas que el
catálogo necesita: qué políticas son evaluables para un cliente sin perfil, si una
política es de Context o de Behavioral, y la validación de que ninguna abarque los
dos nodos. La alternativa —deducirlo de la firma de Python— dejaría el mismo dato
en dos lugares sin nada que los amarre.

**Cada predicado devuelve evidencia, no un booleano.** `Signal.description` es un
campo del contrato que el analista lee en la cola HITL: *"Monto 4500.00 PEN supera
3600.00 (3× el promedio habitual)"* dice algo; *"monto fuera de rango"* no. Y
`observed` le da al Arbiter los números con los que ADR-0006 le pide justificar el
ajuste de confianza, y al monitoreo del entregable 6 la distribución de *por
cuánto* se pasó el umbral —donde el drift se ve antes de que cambien los conteos—.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Callable, Literal
from zoneinfo import ZoneInfo

from multiagent_fraud_detection.domain.params import (
    SEGMENT_AVG_REF,
    from_reference,
)
from multiagent_fraud_detection.enums import Severity

# --------------------------------------------------------------------------- #
# Contexto de evaluación
# --------------------------------------------------------------------------- #

#: Los insumos que un predicado puede pedir. Un predicado sólo puede pedir de
#: acá, y el catálogo valida contra esta lista al cargar.
Input = Literal[
    "transaction",
    "profile",
    "history_customer",
    "history_device",
    "blacklist",
]

#: Insumos que **no** dependen del cliente. Una política cuyos predicados sólo
#: piden de acá es de Transaction Context; cualquier otra, de Behavioral Pattern.
CONTEXT_INPUTS: frozenset[Input] = frozenset({"transaction", "blacklist"})


@dataclass(frozen=True, slots=True)
class EvalContext:
    """Todo lo que los predicados pueden mirar, ya cargado.

    `profile` es `None` cuando el cliente no tiene perfil —~96 transacciones del
    dataset—. No es un error: es el escenario que el contrato llama *el que más
    importa*. Las políticas que dependen del perfil simplemente no se evalúan, y
    el despacho lo resuelve `requires`, no un `if` en cada predicado.

    Los historiales llegan **acotados por la ventana más ancha del catálogo** y
    ordenados cronológicamente, sin incluir la transacción bajo análisis. El
    invariante *as-of* lo garantiza el repositorio (ADR-0004): acá ya está
    cumplido.
    """

    transaction: Any
    profile: Any | None = None
    history_customer: tuple[Any, ...] = ()
    history_device: tuple[Any, ...] = ()
    blacklist: frozenset[str] = frozenset()

    @property
    def available(self) -> frozenset[Input]:
        """Insumos realmente disponibles para este caso."""
        base = {"transaction", "blacklist", "history_customer", "history_device"}
        if self.profile is not None:
            base.add("profile")
        return frozenset(base)  # type: ignore[arg-type]

    @property
    def local_time(self) -> datetime:
        """Hora local del cliente. Requiere perfil: la zona vive en el perfil."""
        return self.transaction.timestamp.astimezone(ZoneInfo(self.profile.timezone))


@dataclass(frozen=True, slots=True)
class Hit:
    """Un predicado que se cumplió, con la evidencia de por qué.

    `detail` va a `Signal.description` y lo lee un humano. `observed` va al
    Arbiter y al monitoreo, y tiene que ser serializable a JSON: nada de
    `Decimal` ni `datetime` crudos.
    """

    detail: str
    observed: dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Especificación de parámetros (introspectable)
# --------------------------------------------------------------------------- #
#
# Los parámetros se declaran como dato y no sólo como firma de Python porque el
# dashboard arma su compositor desde `GET /api/v1/predicates`. Si la lista
# viviera en el frontend habría dos fuentes de verdad para lo mismo.


@dataclass(frozen=True, slots=True)
class ParamSpec:
    kind: Literal["number", "integer", "choice"]
    label: str
    minimum: float | None = None
    maximum: float | None = None
    choices: tuple[str, ...] = ()

    def validate(self, name: str, value: Any) -> None:
        if self.kind == "choice":
            if value not in self.choices:
                raise ValueError(f"{name}={value!r} no está en {self.choices}")
            return
        if self.kind == "integer" and not isinstance(value, int):
            raise ValueError(f"{name}={value!r} debe ser entero")
        if not isinstance(value, (int, float)):
            raise ValueError(f"{name}={value!r} debe ser numérico")
        if self.minimum is not None and value < self.minimum:
            raise ValueError(f"{name}={value} es menor que {self.minimum}")
        if self.maximum is not None and value > self.maximum:
            raise ValueError(f"{name}={value} es mayor que {self.maximum}")


def number(label: str, *, minimum=None, maximum=None) -> ParamSpec:
    return ParamSpec("number", label, minimum, maximum)


def integer(label: str, *, minimum=None, maximum=None) -> ParamSpec:
    return ParamSpec("integer", label, minimum, maximum)


def choice(label: str, *options: str) -> ParamSpec:
    return ParamSpec("choice", label, choices=options)


# --------------------------------------------------------------------------- #
# Registro
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Predicate:
    name: str
    fn: Callable[..., Hit | None]
    requires: frozenset[Input]
    signal: str | Callable[..., str]
    severity: Severity
    params: dict[str, ParamSpec]
    description: str

    #: ¿La observación significa algo **por sí sola**?
    #:
    #: Casi todas sí: "dispositivo nuevo" es información aunque su política no
    #: matchee. Pero un umbral absoluto bajo se cumple en la mayoría de las
    #: transacciones y sólo discrimina acompañado —"monto sobre 135 USD" no dice
    #: nada; "sobre 135 USD **en un comercio de la lista negra**" sí—. Una señal
    #: con 90% de tasa base no es evidencia: es ruido que inunda la tabla que el
    #: entregable 6 vigila y el prompt que el Arbiter lee.
    #:
    #: Las no-standalone se emiten sólo si su política matcheó completa.
    standalone: bool = True

    def signal_code(self, **params: Any) -> str:
        """El código de señal, que en algunos predicados depende del parámetro.

        `count_in_window` emite `DEVICE_VELOCITY` o `CUSTOMER_VELOCITY` según el
        eje. El mapa vive acá y no en la vinculación a propósito: si el código
        fuera campo libre, el vocabulario que el entregable 6 vigila lo
        escribiría quien traduce una política.
        """
        return self.signal(**params) if callable(self.signal) else self.signal

    def is_context(self) -> bool:
        return self.requires <= CONTEXT_INPUTS


LIBRARY: dict[str, Predicate] = {}


def predicate(*, name, requires, signal, severity, params=None, description="",
              standalone=True):
    def wrap(fn: Callable[..., Hit | None]) -> Callable[..., Hit | None]:
        if name in LIBRARY:
            raise RuntimeError(f"predicado duplicado: {name}")
        LIBRARY[name] = Predicate(
            name=name,
            fn=fn,
            requires=frozenset(requires),
            signal=signal,
            severity=severity,
            params=params or {},
            description=description or (fn.__doc__ or "").strip().split("\n")[0],
            standalone=standalone,
        )
        return fn

    return wrap


def _d(value: float | int) -> Decimal:
    """Parámetro numérico a `Decimal`, vía `str` para no arrastrar binario."""
    return Decimal(str(value))


# --------------------------------------------------------------------------- #
# 1. Comparación puntual (transacción + perfil)
# --------------------------------------------------------------------------- #


@predicate(
    name="amount_over_avg_multiple",
    requires=("transaction", "profile"),
    signal="AMOUNT_OVER_USUAL_AVG",
    severity=Severity.MEDIUM,
    params={"factor": number("múltiplo del promedio habitual", minimum=1.0)},
)
def amount_over_avg_multiple(ctx: EvalContext, *, factor: float) -> Hit | None:
    """El monto supera N veces el promedio habitual del cliente."""
    umbral = ctx.profile.usual_amount_avg * _d(factor)
    monto = ctx.transaction.amount
    if monto <= umbral:
        return None
    return Hit(
        detail=(
            f"Monto {monto} {ctx.transaction.currency} supera {umbral} "
            f"({factor}× el promedio habitual de {ctx.profile.usual_amount_avg})"
        ),
        observed={
            "amount": str(monto),
            "threshold": str(umbral),
            "usual_avg": str(ctx.profile.usual_amount_avg),
            "factor": factor,
            "ratio": float(monto / ctx.profile.usual_amount_avg),
        },
    )


@predicate(
    name="amount_over_absolute",
    requires=("transaction",),
    signal="AMOUNT_OVER_ABSOLUTE",
    severity=Severity.LOW,
    params={"threshold_ref": number("umbral en moneda de referencia", minimum=0.0)},
    standalone=False,
)
def amount_over_absolute(ctx: EvalContext, *, threshold_ref: float) -> Hit | None:
    """El monto supera un umbral absoluto, convertido a la moneda del cargo."""
    moneda = ctx.transaction.currency
    umbral = _d(from_reference(threshold_ref, moneda))
    monto = ctx.transaction.amount
    if monto <= umbral:
        return None
    return Hit(
        detail=f"Monto {monto} {moneda} supera el umbral absoluto de {umbral} {moneda}",
        observed={
            "amount": str(monto),
            "threshold": str(umbral),
            "threshold_ref": threshold_ref,
            "currency": moneda,
        },
    )


@predicate(
    name="outside_usual_hours",
    requires=("transaction", "profile"),
    signal="OUTSIDE_USUAL_HOURS",
    severity=Severity.MEDIUM,
)
def outside_usual_hours(ctx: EvalContext) -> Hit | None:
    """La hora local del cliente cae fuera de su ventana habitual.

    La ventana es inclusiva en los dos extremos y admite cruce de medianoche:
    `22-06` es un cliente nocturno válido, no un dato invertido. La hora se
    resuelve en la zona del perfil —el supuesto `America/Lima` está muerto desde
    la etapa de dataset—.
    """
    local = ctx.local_time
    inicio, fin = ctx.profile.usual_hour_start, ctx.profile.usual_hour_end
    hora = local.hour
    dentro = inicio <= hora <= fin if inicio <= fin else (hora >= inicio or hora <= fin)
    if dentro:
        return None
    return Hit(
        detail=(
            f"Hora local {local:%H:%M} ({ctx.profile.timezone}) fuera de la "
            f"ventana habitual {inicio:02d}-{fin:02d}"
        ),
        observed={
            "local_hour": hora,
            "window_start": inicio,
            "window_end": fin,
            "timezone": ctx.profile.timezone,
        },
    )


@predicate(
    name="country_not_usual",
    requires=("transaction", "profile"),
    signal="FOREIGN_COUNTRY",
    severity=Severity.MEDIUM,
)
def country_not_usual(ctx: EvalContext) -> Hit | None:
    """El país del cargo no está entre los habituales del cliente.

    Lista vacía significa que nada está registrado como habitual: todo país es
    ajeno. Eso es señal, no dato inválido.
    """
    habituales = list(ctx.profile.usual_countries or ())
    pais = ctx.transaction.country
    if pais in habituales:
        return None
    return Hit(
        detail=(
            f"País {pais} no figura entre los habituales "
            f"({', '.join(habituales) or 'ninguno registrado'})"
        ),
        observed={"country": pais, "usual_countries": habituales},
    )


@predicate(
    name="device_not_usual",
    requires=("transaction", "profile"),
    signal="NEW_DEVICE",
    severity=Severity.MEDIUM,
)
def device_not_usual(ctx: EvalContext) -> Hit | None:
    """El dispositivo no está entre los habituales del cliente."""
    habituales = list(ctx.profile.usual_devices or ())
    disp = ctx.transaction.device_id
    if disp in habituales:
        return None
    return Hit(
        detail=(
            f"Dispositivo {disp} no figura entre los habituales "
            f"({', '.join(habituales) or 'ninguno registrado'})"
        ),
        observed={"device_id": disp, "usual_devices": habituales},
    )


@predicate(
    name="channel_not_usual",
    requires=("transaction", "profile"),
    signal="NEW_CHANNEL",
    severity=Severity.LOW,
)
def channel_not_usual(ctx: EvalContext) -> Hit | None:
    """El canal difiere del canal habitual del cliente."""
    usual, actual = ctx.profile.usual_channel, ctx.transaction.channel
    if actual == usual:
        return None
    return Hit(
        detail=f"Canal {actual} distinto del habitual ({usual})",
        observed={"channel": str(actual), "usual_channel": str(usual)},
    )


@predicate(
    name="account_age_below",
    requires=("transaction", "profile"),
    signal="NEW_ACCOUNT",
    severity=Severity.LOW,
    params={"days": integer("antigüedad máxima en días", minimum=1)},
)
def account_age_below(ctx: EvalContext, *, days: int) -> Hit | None:
    """La cuenta se abrió hace menos de N días."""
    apertura = datetime.combine(
        ctx.profile.account_creation_date,
        datetime.min.time(),
        tzinfo=ctx.transaction.timestamp.tzinfo,
    )
    edad = (ctx.transaction.timestamp - apertura).days
    if edad >= days:
        return None
    return Hit(
        detail=f"Cuenta abierta hace {edad} días (umbral: {days})",
        observed={
            "account_age_days": edad,
            "threshold_days": days,
            "created_at": ctx.profile.account_creation_date.isoformat(),
        },
    )


@predicate(
    name="amount_over_segment_multiple",
    requires=("transaction", "profile"),
    signal="AMOUNT_OVER_SEGMENT_AVG",
    severity=Severity.MEDIUM,
    params={"factor": number("múltiplo del promedio del segmento", minimum=1.0)},
)
def amount_over_segment_multiple(ctx: EvalContext, *, factor: float) -> Hit | None:
    """El monto supera N veces el promedio del segmento comercial del cliente.

    El promedio está **congelado** en `params.SEGMENT_AVG_REF`, no se consulta:
    derivarlo de la población movería el umbral al agregar un perfil y las
    etiquetas cambiarían sin que nadie tocara una política.
    """
    segmento = str(ctx.profile.segment)
    moneda = ctx.profile.currency
    base = _d(from_reference(SEGMENT_AVG_REF[segmento], moneda))
    umbral = base * _d(factor)
    monto = ctx.transaction.amount
    if monto <= umbral:
        return None
    return Hit(
        detail=(
            f"Monto {monto} {moneda} supera {umbral} ({factor}× el promedio del "
            f"segmento {segmento}, {base} {moneda})"
        ),
        observed={
            "amount": str(monto),
            "threshold": str(umbral),
            "segment": segmento,
            "segment_avg": str(base),
            "factor": factor,
        },
    )


@predicate(
    name="profile_changed_within",
    requires=("transaction", "profile"),
    signal="RECENT_PROFILE_CHANGE",
    severity=Severity.HIGH,
    params={"minutes": integer("ventana en minutos desde el cambio", minimum=1)},
)
def profile_changed_within(ctx: EvalContext, *, minutes: int) -> Hit | None:
    """El cargo ocurre dentro de los N minutos posteriores a un cambio de perfil.

    Sólo cuenta hacia adelante: un cambio *posterior* al cargo no lo explica.
    """
    delta = ctx.transaction.timestamp - ctx.profile.last_profile_update
    if not (timedelta(0) <= delta <= timedelta(minutes=minutes)):
        return None
    transcurridos = int(delta.total_seconds() // 60)
    return Hit(
        detail=(
            f"Cargo a {transcurridos} min de un cambio de perfil "
            f"(ventana: {minutes} min)"
        ),
        observed={
            "minutes_since_change": transcurridos,
            "window_minutes": minutes,
            "changed_at": ctx.profile.last_profile_update.isoformat(),
        },
    )


# --------------------------------------------------------------------------- #
# 2. Lookup en tabla de gobernanza
# --------------------------------------------------------------------------- #


@predicate(
    name="merchant_blacklisted",
    requires=("transaction", "blacklist"),
    signal="MERCHANT_BLACKLISTED",
    severity=Severity.HIGH,
)
def merchant_blacklisted(ctx: EvalContext) -> Hit | None:
    """El comercio está en la lista negra vigente."""
    comercio = ctx.transaction.merchant_id
    if comercio not in ctx.blacklist:
        return None
    return Hit(
        detail=f"Comercio {comercio} está en la lista negra",
        observed={"merchant_id": comercio},
    )


# --------------------------------------------------------------------------- #
# 3. Secuencia (historial as-of)
# --------------------------------------------------------------------------- #
#
# Los cuatro filtran en memoria sobre lo que el repositorio ya trajo. Ninguno
# consulta: el `as_of` no es negociable desde acá, lo fijó quien cargó el
# contexto con el timestamp de la transacción bajo análisis.


def _within(previas, as_of: datetime, minutes: int):
    """Transacciones estrictamente dentro de la ventana hacia atrás."""
    corte = timedelta(minutes=minutes)
    return [t for t in previas if timedelta(0) <= as_of - t.timestamp < corte]


@predicate(
    name="count_in_window",
    requires=("transaction", "history_device", "history_customer"),
    signal=lambda axis, **_: (
        "DEVICE_VELOCITY" if axis == "device" else "CUSTOMER_VELOCITY"
    ),
    severity=Severity.HIGH,
    params={
        "axis": choice("eje de agrupación", "device", "customer"),
        "window_minutes": integer("ventana en minutos", minimum=1),
        "min_count": integer("mínimo de transacciones, incluida ésta", minimum=2),
    },
)
def count_in_window(
    ctx: EvalContext, *, axis: str, window_minutes: int, min_count: int
) -> Hit | None:
    """N o más transacciones sobre el mismo eje dentro de una ventana corta.

    Con `axis="device"` la cuenta **cruza cuentas**: un dispositivo operando
    varios clientes a la vez es justamente lo que la política busca, y filtrar
    por cliente lo escondería.
    """
    previas = ctx.history_device if axis == "device" else ctx.history_customer
    if axis == "device":
        previas = [t for t in previas if t.device_id == ctx.transaction.device_id]
    else:
        previas = [t for t in previas if t.customer_id == ctx.transaction.customer_id]
    ventana = _within(previas, ctx.transaction.timestamp, window_minutes)
    total = len(ventana) + 1
    if total < min_count:
        return None
    return Hit(
        detail=(
            f"{total} transacciones del mismo {axis} en menos de "
            f"{window_minutes} min (umbral: {min_count})"
        ),
        observed={
            "axis": axis,
            "count": total,
            "min_count": min_count,
            "window_minutes": window_minutes,
            "transaction_ids": [t.transaction_id for t in ventana],
        },
    )


@predicate(
    name="preceding_micro_charges",
    requires=("transaction", "history_customer"),
    signal="MICRO_CHARGE_SEQUENCE",
    severity=Severity.HIGH,
    params={
        "min_count": integer("mínimo de cargos pequeños previos", minimum=1),
        "ceiling_ref": number("techo del cargo pequeño, en referencia", minimum=0.0),
        "window_minutes": integer("ventana en minutos", minimum=1),
    },
)
def preceding_micro_charges(
    ctx: EvalContext, *, min_count: int, ceiling_ref: float, window_minutes: int
) -> Hit | None:
    """N o más cargos de prueba por montos ínfimos justo antes de éste.

    Es la mitad barata del *card testing*: sola no decide nada. La política que
    la usa la conjuga con un monto atípico —el cobro grande que sigue—.
    """
    techo = _d(from_reference(ceiling_ref, ctx.transaction.currency))
    ventana = _within(
        [t for t in ctx.history_customer if t.customer_id == ctx.transaction.customer_id],
        ctx.transaction.timestamp,
        window_minutes,
    )
    micro = [t for t in ventana if t.amount <= techo]
    if len(micro) < min_count:
        return None
    return Hit(
        detail=(
            f"{len(micro)} cargos ≤ {techo} {ctx.transaction.currency} en los "
            f"últimos {window_minutes} min (umbral: {min_count})"
        ),
        observed={
            "micro_count": len(micro),
            "min_count": min_count,
            "ceiling": str(techo),
            "window_minutes": window_minutes,
            "transaction_ids": [t.transaction_id for t in micro],
        },
    )


@predicate(
    name="distinct_country_in_window",
    requires=("transaction", "history_customer"),
    signal="IMPOSSIBLE_TRAVEL",
    severity=Severity.HIGH,
    params={"window_minutes": integer("ventana en minutos", minimum=1)},
)
def distinct_country_in_window(ctx: EvalContext, *, window_minutes: int) -> Hit | None:
    """Cargo en un país distinto del anterior dentro de una ventana imposible."""
    ventana = _within(
        [t for t in ctx.history_customer if t.customer_id == ctx.transaction.customer_id],
        ctx.transaction.timestamp,
        window_minutes,
    )
    otros = [t for t in ventana if t.country != ctx.transaction.country]
    if not otros:
        return None
    ultimo = otros[-1]
    minutos = int((ctx.transaction.timestamp - ultimo.timestamp).total_seconds() // 60)
    return Hit(
        detail=(
            f"Cargo en {ctx.transaction.country} a {minutos} min de otro en "
            f"{ultimo.country} (ventana: {window_minutes} min)"
        ),
        observed={
            "country": ctx.transaction.country,
            "previous_country": ultimo.country,
            "minutes_apart": minutos,
            "window_minutes": window_minutes,
            "transaction_ids": [t.transaction_id for t in otros],
        },
    )


@predicate(
    name="daily_sum_over_limit",
    requires=("transaction", "profile", "history_customer"),
    signal="DAILY_LIMIT_EXCEEDED",
    severity=Severity.HIGH,
    params={
        "group_by": choice("eje de agrupación", "merchant"),
        "min_count": integer("mínimo de cargos, incluido éste", minimum=2),
    },
)
def daily_sum_over_limit(
    ctx: EvalContext, *, group_by: str, min_count: int
) -> Hit | None:
    """N o más cargos al mismo comercio en el día local, sumando más que el límite.

    El día es **local del cliente**, no UTC: un fraccionamiento a las 23:00 en
    Lima y otro a las 01:00 no son el mismo día para el cliente aunque UTC los
    junte —o al revés—.
    """
    zona = ZoneInfo(ctx.profile.timezone)
    hoy = ctx.transaction.timestamp.astimezone(zona).date()
    mismas = [
        t
        for t in ctx.history_customer
        if t.customer_id == ctx.transaction.customer_id
        and t.merchant_id == ctx.transaction.merchant_id
        and t.timestamp <= ctx.transaction.timestamp
        and t.timestamp.astimezone(zona).date() == hoy
    ]
    total = len(mismas) + 1
    suma = sum((t.amount for t in mismas), ctx.transaction.amount)
    limite = ctx.profile.daily_limit
    if total < min_count or suma <= limite:
        return None
    return Hit(
        detail=(
            f"{total} cargos a {ctx.transaction.merchant_id} el {hoy} suman "
            f"{suma} {ctx.transaction.currency}, sobre el límite diario de {limite}"
        ),
        observed={
            "count": total,
            "min_count": min_count,
            "sum": str(suma),
            "daily_limit": str(limite),
            "local_date": hoy.isoformat(),
            "group_by": group_by,
            "transaction_ids": [t.transaction_id for t in mismas],
        },
    )
