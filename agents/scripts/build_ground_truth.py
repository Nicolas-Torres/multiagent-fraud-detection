"""Construye el ground truth evaluando el catálogo de políticas sobre el dataset.

    uv run python scripts/build_ground_truth.py   →  data/ground_truth.csv

Una fila por cada una de las 7 000 transacciones, incluidas las limpias: sin
etiqueta negativa no se puede calcular precisión, sólo recall.

Dos principios, y ambos son decisiones de diseño, no detalles:

**Se etiqueta por la regla, no por la intención del generador.** El generador
sabe qué rama sorteó, pero esa información se descarta a propósito. Con
confusores en el dataset, un patrón "normal" puede satisfacer una política por
accidente —una compra cualquiera a 20 minutos de un cambio de perfil—. Si la
etiqueta viniera de la rama, ese caso quedaría marcado APPROVE siendo un
positivo real, y el harness castigaría al sistema por acertar.

**Se evalúa *as-of*, nunca con el futuro.** Cada transacción se juzga con lo que
existía en el instante en que ocurrió. Por eso en una ráfaga sólo la
transacción que *completa* el patrón lleva la etiqueta: cuando llegó la primera,
la ráfaga todavía no existía y APPROVE era la respuesta correcta. Es el mismo
invariante que las consultas de historial del grafo tienen que respetar.

FP-10 (alerta externa sobre el emisor/BIN) no se evalúa: su evidencia es
búsqueda web real, no reproducible desde el dataset. El harness nunca la espera.

Columnas de salida:
    transaction_id      clave
    expected_policies   lista separada por `;`, vacía si ninguna aplica
    expected_decision   APPROVE | CHALLENGE | BLOCK | ESCALATE_TO_HUMAN
    fraud_group_id      grupo(s) en patrones multi-transacción, lista `;`
    is_closing          `true` en la transacción que completa algún patrón
"""

import sys
from collections import defaultdict
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[1] / "data"

BLACKLISTED_MERCHANTS = {"M-999"}

CURRENCY_FACTOR = {
    "PEN": 3.7, "USD": 1.0, "COP": 4000.0, "EUR": 0.9,
    "MXN": 18.0, "ARS": 1000.0, "CLP": 900.0,
}

MICRO_CHARGE_USD = 1.0      # techo del "cobro de centavos" de FP-04
FP07_THRESHOLD_USD = 135.0  # los "500 soles" de FP-07

# La acción que cada política prescribe. El ground truth es lo que el catálogo
# manda hacer, no lo que en retrospectiva resultó ser fraude.
POLICY_ACTION = {
    "FP-01": "CHALLENGE",
    "FP-02": "ESCALATE_TO_HUMAN",
    "FP-03": "BLOCK",
    "FP-04": "BLOCK",
    "FP-05": "ESCALATE_TO_HUMAN",
    "FP-06": "CHALLENGE",
    "FP-07": "ESCALATE_TO_HUMAN",
    "FP-08": "ESCALATE_TO_HUMAN",
    "FP-09": "BLOCK",
    "FP-11": "BLOCK",
}

# Cuando dos políticas aplican a la vez gana la más restrictiva. La misma regla
# tiene que usar el Arbiter, o la comparación contra el ground truth es injusta.
PRECEDENCE = ["BLOCK", "ESCALATE_TO_HUMAN", "CHALLENGE", "APPROVE"]


def _en_ventana(hora, inicio, fin):
    if inicio <= fin:
        return inicio <= hora <= fin
    return hora >= inicio or hora <= fin


def _lista(celda):
    return [x for x in celda.split(";") if x]


def build(tx: pd.DataFrame, cb: pd.DataFrame) -> pd.DataFrame:
    perfiles = {row.customer_id: row for row in cb.itertuples(index=False)}

    # Promedio por segmento en la moneda de cada cuenta: es contra esto que
    # compara FP-08, no contra el promedio del propio cliente.
    base_usd = cb.usual_amount_avg.astype(float) / cb.currency.map(CURRENCY_FACTOR)
    seg_avg_usd = base_usd.groupby(cb.segment).mean().to_dict()

    tx = tx.copy()
    tx["ts_utc"] = pd.to_datetime(tx.timestamp, utc=True, format="ISO8601")
    tx = tx.sort_values("ts_utc").reset_index(drop=True)

    policies = defaultdict(list)     # transaction_id -> [FP-xx]
    grupos_de = defaultdict(list)    # transaction_id -> [G-xxxx]
    cierra = set()                   # transaction_id que completan un patrón
    grupo_seq = 0

    def marcar_grupo(ids, cierre):
        """Una transacción puede pertenecer a más de un grupo: la última de una
        ráfaga puede además cerrar un fraccionamiento. Por eso es una lista y
        no un escalar — un `fraud_group_id` único perdería uno de los dos."""
        nonlocal grupo_seq
        grupo_seq += 1
        gid = f"G-{grupo_seq:04d}"
        for tid in ids:
            grupos_de[tid].append(gid)
        cierra.add(cierre)

    # Historial por cliente, en orden. Cada regla mira sólo hacia atrás.
    por_cliente = defaultdict(list)

    for fila in tx.itertuples(index=False):
        tid = fila.transaction_id
        perfil = perfiles.get(fila.customer_id)
        monto = float(fila.amount)
        previas = por_cliente[fila.customer_id]

        if perfil is None:
            # Cliente sin perfil: sólo son evaluables las políticas que no
            # dependen del historial de comportamiento.
            if fila.merchant_id in BLACKLISTED_MERCHANTS:
                factor = CURRENCY_FACTOR.get(fila.currency, 1.0)
                if monto > FP07_THRESHOLD_USD * factor:
                    policies[tid].append("FP-07")
            por_cliente[fila.customer_id].append((fila, monto))
            continue

        promedio = float(perfil.usual_amount_avg)
        limite = float(perfil.daily_limit)
        factor = CURRENCY_FACTOR[perfil.currency]
        zona = ZoneInfo(perfil.timezone)
        local = fila.ts_utc.astimezone(zona)
        inicio, fin = map(int, perfil.usual_hours.split("-"))

        habituales_pais = _lista(perfil.usual_countries)
        habituales_disp = _lista(perfil.usual_devices)

        # Una lista vacía significa que nada está registrado como habitual, así
        # que todo es nuevo. El contrato lo dice para dispositivos ("todo
        # dispositivo es nuevo → eso es señal"); se aplica igual a países.
        pais_ajeno = fila.country not in habituales_pais
        disp_nuevo = fila.device_id not in habituales_disp

        fuera_horario = not _en_ventana(local.hour, inicio, fin)

        # --- FP-01: monto > 3x y fuera de la ventana horaria ---------------
        if monto > 3 * promedio and fuera_horario:
            policies[tid].append("FP-01")

        # --- FP-02: internacional + dispositivo nuevo -----------------------
        if pais_ajeno and disp_nuevo:
            policies[tid].append("FP-02")

        # --- FP-03: más de 3 transacciones del mismo dispositivo en < 5 min -
        ventana = [
            f for f, _ in previas
            if f.device_id == fila.device_id
            and fila.ts_utc - f.ts_utc < timedelta(minutes=5)
        ]
        if len(ventana) + 1 > 3:
            policies[tid].append("FP-03")
            marcar_grupo([f.transaction_id for f in ventana] + [tid], tid)

        # --- FP-04: 2+ cobros de centavos y luego uno grande, en < 10 min ---
        techo_micro = MICRO_CHARGE_USD * factor
        micro = [
            f for f, m in previas
            if m <= techo_micro and fila.ts_utc - f.ts_utc < timedelta(minutes=10)
        ]
        if len(micro) >= 2 and monto > 2 * promedio:
            policies[tid].append("FP-04")
            marcar_grupo([f.transaction_id for f in micro] + [tid], tid)

        # --- FP-05: dos países incompatibles en menos de 2 h ----------------
        lejos = [
            f for f, _ in previas
            if f.country != fila.country
            and fila.ts_utc - f.ts_utc < timedelta(hours=2)
        ]
        if lejos:
            policies[tid].append("FP-05")
            marcar_grupo([lejos[-1].transaction_id, tid], tid)

        # --- FP-06: canal distinto del habitual y monto > 2x ----------------
        if fila.chanel != perfil.usual_channel and monto > 2 * promedio:
            policies[tid].append("FP-06")

        # --- FP-07: comercio en lista negra sobre el umbral -----------------
        if (fila.merchant_id in BLACKLISTED_MERCHANTS
                and monto > FP07_THRESHOLD_USD * factor):
            policies[tid].append("FP-07")

        # --- FP-08: cuenta de menos de 30 días y monto > 5x del segmento ----
        apertura = pd.Timestamp(perfil.account_creation_date, tz="UTC")
        edad = (fila.ts_utc - apertura).days
        umbral_segmento = seg_avg_usd[perfil.segment] * factor
        if edad < 30 and monto > 5 * umbral_segmento:
            policies[tid].append("FP-08")

        # --- FP-09: transacción dentro de los 30 min de un cambio de perfil -
        cambio = pd.Timestamp(perfil.last_profile_update, tz=zona).astimezone(
            fila.ts_utc.tzinfo
        )
        if timedelta(0) <= fila.ts_utc - cambio <= timedelta(minutes=30):
            policies[tid].append("FP-09")

        # --- FP-11: 3+ pagos al mismo comercio el mismo día sobre el límite -
        mismo_dia = [
            (f, m) for f, m in previas
            if f.merchant_id == fila.merchant_id
            and f.ts_utc.astimezone(zona).date() == local.date()
        ]
        if len(mismo_dia) + 1 >= 3 and sum(m for _, m in mismo_dia) + monto > limite:
            policies[tid].append("FP-11")
            marcar_grupo([f.transaction_id for f, _ in mismo_dia] + [tid], tid)

        por_cliente[fila.customer_id].append((fila, monto))

    filas = []
    for fila in tx.itertuples(index=False):
        tid = fila.transaction_id
        aplicables = policies.get(tid, [])
        acciones = {POLICY_ACTION[p] for p in aplicables}
        decision = next((a for a in PRECEDENCE if a in acciones), "APPROVE")
        filas.append({
            "transaction_id": tid,
            "expected_policies": ";".join(sorted(aplicables)),
            "expected_decision": decision,
            "fraud_group_id": ";".join(grupos_de.get(tid, [])),
            "is_closing": "true" if tid in cierra else "false",
        })

    return pd.DataFrame(filas)


def main() -> int:
    ruta_cb = DATA_DIR / "customer_behaviors.csv"
    ruta_tx = DATA_DIR / "transactions.csv"
    for ruta in (ruta_cb, ruta_tx):
        if not ruta.exists():
            print(f"FALTA {ruta} — corre antes scripts/generate_data.py")
            return 1

    cb = pd.read_csv(ruta_cb, dtype=str, keep_default_na=False)
    tx = pd.read_csv(ruta_tx, dtype=str, keep_default_na=False)

    gt = build(tx, cb)
    gt.to_csv(DATA_DIR / "ground_truth.csv", index=False)

    conteo = (gt.expected_policies.str.split(";").explode()
              .replace("", pd.NA).dropna().value_counts().sort_index())
    print(f"{len(gt)} etiquetas -> {DATA_DIR / 'ground_truth.csv'}")
    print("\npositivos por política:")
    for pol, n in conteo.items():
        print(f"  {pol}: {n}")
    print("\ndecisión esperada:")
    for dec, n in gt.expected_decision.value_counts().items():
        print(f"  {dec}: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
