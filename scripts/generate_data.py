"""Generador del dataset sintético de detección de fraude.

Produce dos archivos en `data/`:

    customer_behaviors.csv   1 000 perfiles de comportamiento
    transactions.csv         7 000 transacciones

Determinista: `np.random.seed(42)` usa el RandomState legado, cuyo stream numpy
congeló por política de compatibilidad. Regenerar produce los mismos bytes
incluso con otra versión de numpy o pandas.

Convenciones del CSV:
    - Las listas van separadas por `;` sin espacios ("PE;ES").
    - Una lista vacía es una celda vacía → al leer hace falta
      `keep_default_na=False`, si no pandas la convierte en NaN.
    - `timestamp` es UTC con offset explícito ("2025-12-14T03:15:00+00:00").
      Se construye en la hora local del cliente y se convierte: la ventana
      `usual_hours` es local, así que un agente que ignore `timezone` evalúa
      otra cosa. Ese es el punto.

El dataset no trae etiquetas. El ground truth se computa aparte, evaluando las
once reglas del catálogo sobre el resultado — no registrando qué rama disparó.
Medir por la regla y no por la intención evita que un solapamiento accidental
quede mal etiquetado.
"""

import random
from datetime import datetime, timedelta, timezone as dt_timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[1] / "data"

# Parametros
NUM_CUSTOMERS = 1000
NUM_TRANSACTIONS = 7000

# Ventana de observación. Todas las transacciones caen acá.
DEC_START = datetime(2025, 12, 1)
DEC_END = datetime(2025, 12, 30)

# Casos límite deliberados. El contrato los declara válidos y el dataset
# original no tenía ninguno, así que el harness no podía probarlos.
P_NOCTURNAL = 0.05        # ventana horaria que cruza medianoche (22-06)
P_EMPTY_DEVICES = 0.03    # "ningún dispositivo habitual" → todo es nuevo
P_EMPTY_COUNTRIES = 0.03  # "ningún país habitual"
P_MULTI_COUNTRY = 0.03    # perfil con dos países
P_NEW_ACCOUNT = 0.12      # cuenta abierta dentro de la ventana reciente

np.random.seed(42)
random.seed(42)

# Moneda, escala y zonas horarias por país.
#
# `factor` convierte un monto expresado en USD a la moneda local. La línea base
# se genera en USD y se multiplica: sin eso un cliente colombiano con promedio
# "1200" tendría medio dólar de promedio. El mismo factor se aplica a
# `usual_amount_avg` y a `daily_limit`, o FP-11 (fraccionamiento) se rompe.
#
# `timezones` es una lista porque US y MX abarcan varias: elegir una sola para
# todo el país metería hasta 3 h de error en la evaluación de FP-01.
COUNTRY_PROFILE = {
    "PE": {
        "currency": "PEN",
        "factor": 3.7,
        "timezones": ["America/Lima"],
    },
    "US": {
        "currency": "USD",
        "factor": 1.0,
        "timezones": [
            "America/New_York",
            "America/Chicago",
            "America/Denver",
            "America/Los_Angeles",
        ],
    },
    "CO": {
        "currency": "COP",
        "factor": 4000.0,
        "timezones": ["America/Bogota"],
    },
    "ES": {
        "currency": "EUR",
        "factor": 0.9,
        "timezones": ["Europe/Madrid"],
    },
    "MX": {
        "currency": "MXN",
        "factor": 18.0,
        "timezones": [
            "America/Mexico_City",
            "America/Tijuana",
            "America/Monterrey",
        ],
    },
    "AR": {
        "currency": "ARS",
        "factor": 1000.0,
        "timezones": ["America/Argentina/Buenos_Aires"],
    },
    "CL": {
        "currency": "CLP",
        "factor": 900.0,
        "timezones": ["America/Santiago"],
    },
}

COUNTRIES = list(COUNTRY_PROFILE)

# Factor de escala indexado por moneda. Lo necesitan tanto el generador como el
# etiquetador: dos políticas tienen umbrales expresados en dinero ("centavos",
# "500 soles") y un umbral monetario sin moneda no significa nada.
CURRENCY_FACTOR = {p["currency"]: p["factor"] for p in COUNTRY_PROFILE.values()}

# Umbrales de política, en USD. Se convierten a la moneda de la cuenta.
MICRO_CHARGE_USD = 0.50    # el "cobro de centavos" de FP-04
FP07_THRESHOLD_USD = 135.0  # los "500 soles" de FP-07

# Segmento comercial. El multiplicador es lo que le da sentido a FP-08
# ("> 5x el promedio típico de su segmento"): si los tres segmentos tuvieran la
# misma distribución, el promedio del segmento sería el promedio global y la
# política no se distinguiría de "5x su propio promedio".
SEGMENTS = [
    ("retail", 0.70, 1.0),
    ("premium", 0.25, 3.0),
    ("business", 0.05, 8.0),
]

# Top 3 bancos de consumo por pais
BANKS_BY_COUNTRY = {
    "PE": ["BCP", "BBVA", "IBK"],     # Banco de Credito, BBVA Peru, Interbank
    "US": ["JPM", "BAC", "WFC"],      # Chase, Bank of America, Wells Fargo
    "CO": ["BAN", "DAV", "BOG"],      # Bancolombia, Davivienda, Banco de Bogota
    "ES": ["SAN", "BBVA", "CABK"],    # Santander, BBVA, CaixaBank
    "MX": ["BBVA", "BAN", "SAN"],     # BBVA Mexico, Banorte, Santander
    "AR": ["BNA", "GAL", "SAN"],      # Banco Nacion, Galicia, Santander
    "CL": ["BCH", "SAN", "BCI"],      # Banco de Chile, Santander, BCI
}

MERCHANTS = [f"M-{i:03d}" for i in range(1, 51)]
BLACKLISTED_MERCHANT = "M-999"

# Presupuesto de patrones, como fracción de los sorteos.
#
# Las once políticas ocupan 1% cada una. Los confusores son la contribución de
# esta etapa: sin ellos, `país ≠ habitual` tiene precisión 1.0 y la métrica no
# distingue un sistema bueno de un `if` de una línea. Se tallan del relleno, no
# se suman encima: el total sigue siendo 7 000.
#
#   CONF-*  señal suelta legítima: dispara una dimensión, ninguna política.
#   NEAR-*  casi-positivo: falla una condición de la política por poco.
PATTERN_WEIGHTS = {
    "FP-01": 0.010,   # monto > 3x y fuera de horario
    "FP-02": 0.010,   # internacional + dispositivo nuevo
    "FP-03": 0.010,   # velocity
    "FP-04": 0.010,   # card testing
    "FP-05": 0.010,   # geolocalización imposible
    "FP-06": 0.010,   # canal nuevo + monto alto
    "FP-07": 0.010,   # comercio en lista negra
    "FP-08": 0.010,   # cuenta nueva + monto > 5x del segmento
    "FP-09": 0.010,   # cambio de datos + transacción inmediata
    "FP-10": 0.010,   # alerta externa (fuera de alcance implementado)
    "FP-11": 0.010,   # fraccionamiento

    "CONF-TRAVEL": 0.020,       # país distinto, dispositivo habitual
    "CONF-NEW-DEVICE": 0.015,   # dispositivo nuevo, país habitual
    "CONF-CHANNEL": 0.010,      # canal distinto, monto normal
    "CONF-BIG-BUY": 0.015,      # monto > 3x dentro de la ventana horaria

    "NEAR-VELOCITY": 0.010,     # 3 tx en 6 min (FP-03 exige >3 en <5)
    "NEAR-CENTS": 0.010,        # 2 cobros de centavos sin el monto grande
    "NEAR-SMURF": 0.010,        # 3 pagos que suman 0.9x el límite
    "NEAR-YOUNG": 0.010,        # cuenta de 31-60 días con monto de 6x

    "NO-PROFILE": 0.020,        # transacción de un cliente sin perfil
}


def _weighted_choice():
    """Elige un patrón según PATTERN_WEIGHTS; el resto del peso es NORMAL."""
    r = random.random()
    acc = 0.0
    for name, weight in PATTERN_WEIGHTS.items():
        acc += weight
        if r < acc:
            return name
    return "NORMAL"


def _pick_segment():
    """Devuelve (nombre, multiplicador de monto) según los pesos de SEGMENTS."""
    r = random.random()
    acc = 0.0
    for name, weight, factor in SEGMENTS:
        acc += weight
        if r < acc:
            return name, factor
    return SEGMENTS[-1][0], SEGMENTS[-1][2]


def _in_window(hour, start, end):
    """¿`hour` cae dentro de la ventana habitual [start, end] inclusive?

    Contempla el cruce de medianoche: para un cliente nocturno (22-06) la
    ventana es {22, 23, 0, 1, ..., 6}, no el complemento.
    """
    if start <= end:
        return start <= hour <= end
    return hour >= start or hour <= end


def _rand_december(hour):
    """Fecha local dentro de la ventana de observación, a la hora indicada."""
    dias = (DEC_END - DEC_START).days
    return DEC_START + timedelta(
        days=int(np.random.randint(0, dias + 1)),
        hours=int(hour),
        minutes=int(np.random.randint(0, 60)),
    )


def _december_date_with_age(creation, min_age, max_age, hour):
    """Fecha en diciembre tal que la cuenta tenga entre min_age y max_age días.

    Devuelve None si no existe ninguna: el llamador vuelve a sortear cliente.
    Es lo que hace evaluable a FP-08. Antes la rama comparaba contra una fecha
    fija y sólo producía un positivo real cuando el cliente sorteado resultaba
    tener cuenta nueva — unos 6 casos en todo el dataset.
    """
    lo = max(DEC_START, creation + timedelta(days=min_age))
    hi = min(DEC_END, creation + timedelta(days=max_age))
    if lo > hi:
        return None
    span = (hi - lo).days
    return (
        lo
        + timedelta(days=int(np.random.randint(0, span + 1)))
        + timedelta(hours=int(hour), minutes=int(np.random.randint(0, 60)))
    )


def generate_customers():
    customers = []

    for i in range(1, NUM_CUSTOMERS + 1):
        c_id = f"CU-{i:04d}"

        country = str(np.random.choice(COUNTRIES))
        profile = COUNTRY_PROFILE[country]

        segment, seg_factor = _pick_segment()

        # Línea base en USD, escalada a la moneda de la cuenta.
        base_usd = np.random.uniform(50, 1200) * seg_factor
        avg_amt = round(base_usd * profile["factor"], 2)
        daily_limit = round(avg_amt * np.random.uniform(3, 8), 2)

        # Ventana horaria. Los nocturnos son el caso `start > end` que el
        # contrato declara válido en §2.5 y que el dataset original no tenía.
        if random.random() < P_NOCTURNAL:
            start_hour = np.random.randint(22, 24)
            end_hour = np.random.randint(5, 8)
        else:
            start_hour = np.random.randint(6, 12)
            end_hour = np.random.randint(18, 23)
        hours = f"{start_hour:02d}-{end_hour:02d}"

        home_device = f"D-{i:04d}"

        # Los tres casos límite se sortean por separado: un cliente puede ser
        # nocturno *y* no tener dispositivos habituales.
        usual_devices = "" if random.random() < P_EMPTY_DEVICES else home_device

        r_country = random.random()
        if r_country < P_EMPTY_COUNTRIES:
            usual_countries = ""
        elif r_country < P_EMPTY_COUNTRIES + P_MULTI_COUNTRY:
            other = str(np.random.choice([c for c in COUNTRIES if c != country]))
            usual_countries = f"{country};{other}"
        else:
            usual_countries = country

        usual_channel = str(np.random.choice(["web", "mobile"]))

        # Cuentas nuevas repartidas entre octubre y mediados de diciembre. El
        # rango ancho es lo que permite construir tanto positivos de FP-08
        # (< 30 días al momento de la transacción) como el casi-positivo de
        # 31-60 días, ambos con la transacción dentro de diciembre.
        if random.random() < P_NEW_ACCOUNT:
            creation_date = datetime(2025, 10, 2) + timedelta(
                days=int(np.random.randint(0, 80))
            )
        else:
            creation_date = datetime(
                2020 + int(np.random.randint(0, 5)),
                int(np.random.randint(1, 13)),
                int(np.random.randint(1, 28)),
            )

        # Dentro de la ventana de observación y nunca antes de la apertura.
        # FP-09 fecha su transacción como `last_profile_update + 10 min`; con
        # este campo a medianoche el dataset original tenía 70 transacciones a
        # las 00:10:00 exactas, huella que un modelo aprende.
        lp_lo = max(creation_date, DEC_START)
        lp_span = max((DEC_END - lp_lo).days, 0)
        last_profile = lp_lo + timedelta(
            days=int(np.random.randint(0, lp_span + 1)),
            hours=int(np.random.randint(0, 24)),
            minutes=int(np.random.randint(0, 60)),
            seconds=int(np.random.randint(0, 60)),
        )

        issuer_bank = str(np.random.choice(BANKS_BY_COUNTRY[country]))

        customers.append({
            "customer_id": c_id,
            "usual_amount_avg": f"{avg_amt:.2f}",
            "usual_hours": hours,
            "usual_countries": usual_countries,
            "usual_devices": usual_devices,
            "usual_channel": usual_channel,
            "account_creation_date": creation_date.strftime("%Y-%m-%d"),
            "last_profile_update": last_profile.strftime("%Y-%m-%dT%H:%M:%S"),
            "issuer_bank": issuer_bank,
            "daily_limit": f"{daily_limit:.2f}",
            "currency": profile["currency"],
            "timezone": str(np.random.choice(profile["timezones"])),
            "segment": segment,
            # Columnas internas: no se emiten al CSV.
            #
            # Que `usual_devices` esté vacío no significa que el cliente no use
            # dispositivos: significa que el perfil no registra ninguno como
            # habitual. Las transacciones igual necesitan un `device_id` real.
            # Lo mismo con el país.
            "_home_country": country,
            "_home_device": home_device,
        })

    return pd.DataFrame(customers)


def _make_tx(t_id, c_id, amt, currency, country, channel, dev, local_dt, tz,
             merch, bank):
    """Construye una transacción. `local_dt` es hora local; se emite en UTC.

    La moneda es la de la cuenta, no la del país donde ocurre la compra: una
    tarjeta liquida en la moneda de su cuenta. La dimensión internacional
    sobrevive porque `country` sigue variando.
    """
    aware = local_dt.replace(tzinfo=ZoneInfo(tz))
    utc = aware.astimezone(dt_timezone.utc)
    return {
        "transaction_id": f"T-{t_id}",
        "customer_id": c_id,
        "amount": f"{amt:.2f}",
        "currency": currency,
        "country": country,
        "chanel": channel,
        "device_id": dev,
        "timestamp": utc.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
        "merchant_id": merch,
        "issuer_bank": bank,
    }


def generate_transactions(customers_df):
    transactions = []
    t_id_counter = 1000

    # Pools para los patrones que necesitan un cliente con una precondición.
    creation = pd.to_datetime(customers_df.account_creation_date)
    pool_new = customers_df[creation >= datetime(2025, 11, 2)]
    pool_young = customers_df[
        (creation >= datetime(2025, 10, 2)) & (creation <= datetime(2025, 11, 29))
    ]

    no_profile_seq = 0

    # Promedio por segmento, que es contra lo que FP-08 compara. Se calcula en
    # USD y se reexpresa en la moneda de cada cuenta: comparar 4 000 COP con
    # 4 000 CLP sería comparar manzanas con peras.
    base_usd = (customers_df.usual_amount_avg.astype(float)
                / customers_df.currency.map(CURRENCY_FACTOR))
    seg_avg_usd = base_usd.groupby(customers_df.segment).mean().to_dict()
    seg_avg_local = {
        (seg, cur): avg * CURRENCY_FACTOR[cur]
        for seg, avg in seg_avg_usd.items()
        for cur in CURRENCY_FACTOR
    }

    def pick(pool=None):
        src = customers_df if pool is None or len(pool) == 0 else pool
        return src.iloc[np.random.randint(0, len(src))]

    i = 0
    while i < NUM_TRANSACTIONS:
        restante = NUM_TRANSACTIONS - i
        pattern = _weighted_choice()

        # Un patrón multi-fila que no cabe se degrada a normal, para que el
        # total sea exactamente 7 000 sin cortar un grupo por la mitad.
        filas = {"FP-03": 4, "FP-04": 3, "FP-05": 2, "FP-11": 3,
                 "NEAR-VELOCITY": 3, "NEAR-CENTS": 2, "NEAR-SMURF": 3}.get(pattern, 1)
        if filas > restante:
            pattern = "NORMAL"
            filas = 1

        # --- cliente sin perfil: no hay fila en customer_behaviors -----------
        if pattern == "NO-PROFILE":
            no_profile_seq += 1
            country = str(np.random.choice(COUNTRIES))
            cp = COUNTRY_PROFILE[country]
            tz = str(np.random.choice(cp["timezones"]))
            t_id_counter += 1
            # Una fracción cae en el comercio de lista negra: FP-07 no necesita
            # perfil, así que el sistema debe poder aplicarla igual.
            merch = (BLACKLISTED_MERCHANT if random.random() < 0.15
                     else str(np.random.choice(MERCHANTS)))
            transactions.append(_make_tx(
                t_id_counter, f"CU-9{no_profile_seq:03d}",
                round(np.random.uniform(50, 1500) * cp["factor"], 2),
                cp["currency"], country,
                str(np.random.choice(["web", "mobile"])),
                f"D-8{np.random.randint(100, 999)}",
                _rand_december(np.random.randint(8, 21)), tz,
                merch, str(np.random.choice(BANKS_BY_COUNTRY[country])),
            ))
            i += 1
            continue

        # --- selección de cliente según la precondición del patrón -----------
        if pattern == "FP-08":
            customer = pick(pool_new)
        elif pattern == "NEAR-YOUNG":
            customer = pick(pool_young)
        else:
            customer = pick()

        c_id = customer["customer_id"]
        avg_amt = float(customer["usual_amount_avg"])
        u_hours = customer["usual_hours"]
        u_country = customer["_home_country"]
        u_device = customer["_home_device"]
        u_channel = customer["usual_channel"]
        u_currency = customer["currency"]
        u_tz = customer["timezone"]
        c_date = datetime.strptime(customer["account_creation_date"], "%Y-%m-%d")
        last_profile = datetime.strptime(
            customer["last_profile_update"], "%Y-%m-%dT%H:%M:%S"
        )
        u_bank = customer["issuer_bank"]
        daily_limit = float(customer["daily_limit"])
        factor = CURRENCY_FACTOR[u_currency]
        micro = round(MICRO_CHARGE_USD * factor, 2)
        seg_avg = seg_avg_local[(customer["segment"], u_currency)]
        usual_countries = (
            customer["usual_countries"].split(";")
            if customer["usual_countries"] else []
        )

        start_h, end_h = map(int, u_hours.split("-"))
        hours_in = [h for h in range(24) if _in_window(h, start_h, end_h)]
        hours_out = [h for h in range(24) if not _in_window(h, start_h, end_h)]

        def tx(t_id, amt, country, channel, dev, local_dt, merch=None):
            return _make_tx(
                t_id, c_id, amt, u_currency, country, channel, dev, local_dt,
                u_tz, merch or str(np.random.choice(MERCHANTS)), u_bank,
            )

        t_id_counter += 1

        # ------------------------------------------------------ políticas ---
        if pattern == "FP-01":
            # Monto > 3x y fuera de horario
            amt = round(avg_amt * np.random.uniform(3.5, 5.0), 2)
            t_date = _rand_december(np.random.choice(hours_out))
            transactions.append(tx(t_id_counter, amt, u_country, u_channel,
                                   u_device, t_date))
            i += 1

        elif pattern == "FP-02":
            # Internacional + dispositivo nuevo
            amt = round(avg_amt * np.random.uniform(0.5, 1.5), 2)
            t_date = _rand_december(np.random.choice(hours_in))
            transactions.append(tx(t_id_counter, amt, "RU", u_channel,
                                   f"D-999{np.random.randint(100, 999)}", t_date))
            i += 1

        elif pattern == "FP-03":
            # Velocity: 4 tx en 4 min, mismo dispositivo
            t_date = _rand_december(12)
            merch = str(np.random.choice(MERCHANTS))
            for j in range(4):
                t_date += timedelta(minutes=1)
                transactions.append(tx(
                    t_id_counter + j,
                    round(avg_amt * np.random.uniform(0.1, 0.5), 2),
                    u_country, u_channel, u_device, t_date, merch,
                ))
            t_id_counter += 3
            i += 4

        elif pattern == "FP-04":
            # Card testing: 2 cobros de centavos y luego uno grande, < 10 min
            t_date = _rand_december(14)
            dev = f"D-999{np.random.randint(100, 999)}"
            for j in range(2):
                transactions.append(tx(t_id_counter + j, micro, u_country,
                                       u_channel, dev,
                                       t_date + timedelta(minutes=j * 2)))
            transactions.append(tx(t_id_counter + 2, round(avg_amt * 4, 2),
                                   u_country, u_channel, dev,
                                   t_date + timedelta(minutes=6)))
            t_id_counter += 2
            i += 3

        elif pattern == "FP-05":
            # Geolocalización imposible: dos países en menos de 2 h
            t_date = _rand_december(10)
            a, b = "PE", "ES"
            transactions.append(tx(t_id_counter, avg_amt, a, u_channel,
                                   u_device, t_date))
            transactions.append(tx(t_id_counter + 1, avg_amt, b, u_channel,
                                   u_device, t_date + timedelta(hours=1, minutes=30)))
            t_id_counter += 1
            i += 2

        elif pattern == "FP-06":
            # Canal nuevo con monto alto (> 2x)
            amt = round(avg_amt * np.random.uniform(2.1, 3.5), 2)
            other_channel = "mobile" if u_channel == "web" else "web"
            t_date = _rand_december(np.random.choice(hours_in))
            transactions.append(tx(t_id_counter, amt, u_country, other_channel,
                                   u_device, t_date))
            i += 1

        elif pattern == "FP-07":
            # Comercio en lista negra
            amt = round(FP07_THRESHOLD_USD * factor * np.random.uniform(1.2, 5.0), 2)
            t_date = _rand_december(np.random.choice(hours_in))
            transactions.append(tx(t_id_counter, amt, u_country, u_channel,
                                   u_device, t_date, BLACKLISTED_MERCHANT))
            i += 1

        elif pattern == "FP-08":
            # Cuenta nueva (< 30 días al momento de la transacción) + monto alto
            t_date = _december_date_with_age(c_date, 1, 29,
                                             np.random.choice(hours_in))
            if t_date is None:
                t_date = _rand_december(np.random.choice(hours_in))
            amt = round(seg_avg * np.random.uniform(5.2, 8.0), 2)
            transactions.append(tx(t_id_counter, amt, u_country, u_channel,
                                   u_device, t_date))
            i += 1

        elif pattern == "FP-09":
            # Cambio de datos + transacción inmediata
            amt = round(avg_amt * np.random.uniform(0.5, 2.0), 2)
            transactions.append(tx(t_id_counter, amt, u_country, u_channel,
                                   u_device, last_profile + timedelta(minutes=10)))
            i += 1

        elif pattern == "FP-10":
            # Alerta externa sobre el emisor/BIN. Fuera del alcance
            # implementado: su evidencia es búsqueda web real, no reproducible.
            amt = round(avg_amt * np.random.uniform(0.5, 1.5), 2)
            t_date = _rand_december(np.random.choice(hours_in))
            transactions.append(tx(t_id_counter, amt, u_country, u_channel,
                                   u_device, t_date))
            i += 1

        elif pattern == "FP-11":
            # Fraccionamiento: 3 pagos al mismo comercio que suman > límite
            t_date = _rand_december(9)
            merch = str(np.random.choice(MERCHANTS))
            amt = round(daily_limit * 0.4, 2)
            for j in range(3):
                transactions.append(tx(t_id_counter + j, amt, u_country,
                                       u_channel, u_device,
                                       t_date + timedelta(hours=j * 2), merch))
            t_id_counter += 2
            i += 3

        # ----------------------------------------- confusores: señal suelta ---
        elif pattern == "CONF-TRAVEL":
            # Viaje legítimo: país distinto, dispositivo y monto habituales.
            # FP-02 exige internacional *y* dispositivo nuevo → no dispara.
            candidatos = [c for c in COUNTRIES
                          if c != u_country and c not in usual_countries]
            amt = round(avg_amt * np.random.uniform(0.6, 1.6), 2)
            t_date = _rand_december(np.random.choice(hours_in))
            transactions.append(tx(t_id_counter, amt,
                                   str(np.random.choice(candidatos)),
                                   u_channel, u_device, t_date))
            i += 1

        elif pattern == "CONF-NEW-DEVICE":
            # Teléfono nuevo, en casa. FP-02 exige que además sea internacional.
            amt = round(avg_amt * np.random.uniform(0.5, 1.5), 2)
            t_date = _rand_december(np.random.choice(hours_in))
            transactions.append(tx(t_id_counter, amt, u_country, u_channel,
                                   f"D-777{np.random.randint(100, 999)}", t_date))
            i += 1

        elif pattern == "CONF-CHANNEL":
            # Canal distinto con monto normal. FP-06 exige monto > 2x.
            amt = round(avg_amt * np.random.uniform(0.5, 1.8), 2)
            other_channel = "mobile" if u_channel == "web" else "web"
            t_date = _rand_december(np.random.choice(hours_in))
            transactions.append(tx(t_id_counter, amt, u_country, other_channel,
                                   u_device, t_date))
            i += 1

        elif pattern == "CONF-BIG-BUY":
            # Compra grande dentro de la ventana. FP-01 exige monto *y* horario.
            amt = round(avg_amt * np.random.uniform(3.2, 6.0), 2)
            t_date = _rand_december(np.random.choice(hours_in))
            transactions.append(tx(t_id_counter, amt, u_country, u_channel,
                                   u_device, t_date))
            i += 1

        # -------------------------------------------- confusores: casi-positivo ---
        elif pattern == "NEAR-VELOCITY":
            # 3 tx en 6 min. FP-03 exige más de 3 en menos de 5.
            t_date = _rand_december(13)
            merch = str(np.random.choice(MERCHANTS))
            for j in range(3):
                transactions.append(tx(
                    t_id_counter + j,
                    round(avg_amt * np.random.uniform(0.2, 0.6), 2),
                    u_country, u_channel, u_device,
                    t_date + timedelta(minutes=j * 3), merch,
                ))
            t_id_counter += 2
            i += 3

        elif pattern == "NEAR-CENTS":
            # Dos cobros de centavos sin el monto grande que cierra FP-04.
            t_date = _rand_december(15)
            dev = f"D-777{np.random.randint(100, 999)}"
            for j in range(2):
                transactions.append(tx(t_id_counter + j, micro, u_country,
                                       u_channel, dev,
                                       t_date + timedelta(minutes=j * 2)))
            t_id_counter += 1
            i += 2

        elif pattern == "NEAR-SMURF":
            # 3 pagos al mismo comercio que suman 0.9x el límite: no lo cruzan.
            t_date = _rand_december(9)
            merch = str(np.random.choice(MERCHANTS))
            amt = round(daily_limit * 0.3, 2)
            for j in range(3):
                transactions.append(tx(t_id_counter + j, amt, u_country,
                                       u_channel, u_device,
                                       t_date + timedelta(hours=j * 2), merch))
            t_id_counter += 2
            i += 3

        elif pattern == "NEAR-YOUNG":
            # Cuenta de 31-60 días con monto de 6x: FP-08 exige menos de 30.
            t_date = _december_date_with_age(c_date, 31, 60,
                                             np.random.choice(hours_in))
            if t_date is None:
                t_date = _rand_december(np.random.choice(hours_in))
            amt = round(seg_avg * np.random.uniform(5.2, 8.0), 2)
            transactions.append(tx(t_id_counter, amt, u_country, u_channel,
                                   u_device, t_date))
            i += 1

        # ------------------------------------------------------- relleno ----
        else:
            amt = round(avg_amt * np.random.uniform(0.5, 1.5), 2)
            t_date = _rand_december(np.random.choice(hours_in))
            transactions.append(tx(t_id_counter, amt, u_country, u_channel,
                                   u_device, t_date))
            i += 1

    return pd.DataFrame(transactions)


if __name__ == "__main__":
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    print("Generando perfiles de comportamiento...")
    df_customers = generate_customers()

    print("Generando transacciones...")
    df_transactions = generate_transactions(df_customers)
    df_transactions = df_transactions.sort_values(by="timestamp").reset_index(drop=True)

    # Las columnas internas (`_home_*`) no salen al CSV: son andamiaje para
    # generar transacciones coherentes con perfiles que tienen listas vacías.
    public_cols = [c for c in df_customers.columns if not c.startswith("_")]
    df_customers[public_cols].to_csv(DATA_DIR / "customer_behaviors.csv", index=False)
    df_transactions.to_csv(DATA_DIR / "transactions.csv", index=False)

    print(f"{len(df_customers)} perfiles      -> {DATA_DIR / 'customer_behaviors.csv'}")
    print(f"{len(df_transactions)} transacciones -> {DATA_DIR / 'transactions.csv'}")
