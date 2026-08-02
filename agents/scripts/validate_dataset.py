"""Verificación del dataset generado, sin base de datos.

Comprueba que los CSV de `data/` cumplen lo que el contrato declara válido y
lo que el harness del entregable 7 necesita. Se corre después de cada
regeneración:

    uv run python scripts/generate_data.py
    uv run python scripts/validate_dataset.py

Devuelve código de salida distinto de cero si hay fallas, lo que lo vuelve
gate de CI sin tocarlo.

Los criterios son rangos y mínimos, no números exactos: los patrones se
sortean con probabilidades, y un `== 50` haría perseguir un falso fallo.

Crece con la etapa: `check_ground_truth` en 1.3.
"""

import sys
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[1] / "data"

SEGMENTS_ESPERADOS = {"retail", "premium", "business"}

# Un confusor no sirve si la señal que activa sigue siendo un predictor casi
# perfecto. Este es el piso de población benigna por dimensión.
FRACCION_BENIGNA_MINIMA = 0.20


def _rango(fallas, etiqueta, valor, minimo, maximo):
    if not (minimo <= valor <= maximo):
        fallas.append(f"{etiqueta}: {valor} (esperado entre {minimo} y {maximo})")


def _minimo(fallas, etiqueta, valor, minimo):
    if valor < minimo:
        fallas.append(f"{etiqueta}: {valor} (esperado al menos {minimo})")


def _en_ventana(hora, inicio, fin):
    """Contempla el cruce de medianoche del cliente nocturno."""
    if inicio <= fin:
        return inicio <= hora <= fin
    return hora >= inicio or hora <= fin


def check_profiles(cb: pd.DataFrame) -> list[str]:
    """Devuelve la lista de fallas. Vacía significa que todo pasó."""
    fallas: list[str] = []

    # Casos límite que el contrato declara válidos (§2.5) y que el dataset
    # original no ejercitaba en absoluto.
    horas = cb.usual_hours.str.split("-", expand=True).astype(int)
    _rango(fallas, "clientes nocturnos (start > end)",
           int((horas[0] > horas[1]).sum()), 40, 60)

    _rango(fallas, "usual_devices vacíos",
           int((cb.usual_devices == "").sum()), 20, 40)

    _rango(fallas, "usual_countries vacíos",
           int((cb.usual_countries == "").sum()), 20, 40)

    _minimo(fallas, "perfiles multi-país",
            int(cb.usual_countries.str.contains(";").sum()), 20)

    # Los tres segmentos tienen que existir, o FP-08 evalúa contra un promedio
    # de segmento que no se distingue del promedio global.
    presentes = set(cb.segment.unique())
    if presentes != SEGMENTS_ESPERADOS:
        fallas.append(
            f"segmentos: {sorted(presentes)} (esperado {sorted(SEGMENTS_ESPERADOS)})"
        )

    # La zona horaria es la que decide si FP-01 evalúa la ventana correcta.
    # Un "America/Mexico City" con espacio no falla hasta que corre el agente.
    for zona in sorted(cb.timezone.unique()):
        try:
            ZoneInfo(zona)
        except (ZoneInfoNotFoundError, ValueError):
            fallas.append(f"zona horaria inválida: {zona!r}")

    # Ancho uniforme de identificadores: 'CU-0001', no 'CU-001' junto a 'CU-1000'.
    anchos = set(cb.customer_id.str.len().unique())
    if anchos != {7}:
        fallas.append(f"ancho de customer_id: {sorted(anchos)} (esperado sólo 7)")

    # Coherencia interna: una cuenta tiene una moneda, y las tres columnas
    # nuevas no admiten huecos.
    for columna in ("currency", "timezone", "segment"):
        vacios = int((cb[columna] == "").sum())
        if vacios:
            fallas.append(f"{columna}: {vacios} celdas vacías")

    # Cuentas nuevas suficientes para alimentar FP-08 y su casi-positivo.
    creacion = pd.to_datetime(cb.account_creation_date)
    _minimo(fallas, "cuentas abiertas desde octubre 2025",
            int((creacion >= pd.Timestamp("2025-10-02")).sum()), 60)

    return fallas


def check_transactions(tx: pd.DataFrame, cb: pd.DataFrame) -> list[str]:
    fallas: list[str] = []

    if len(tx) != 7000:
        fallas.append(f"transacciones: {len(tx)} (esperado 7000)")
    if tx.transaction_id.nunique() != len(tx):
        fallas.append("transaction_id duplicados")

    # Offset explícito: un timestamp sin zona en un dataset cuyo problema
    # central es la zona horaria es una mina puesta a mano.
    sin_offset = int((~tx.timestamp.str.endswith("+00:00")).sum())
    if sin_offset:
        fallas.append(f"timestamps sin offset UTC: {sin_offset}")

    utc = pd.to_datetime(tx.timestamp, utc=True, format="ISO8601")

    # La huella del generador original: 70 transacciones a las 00:10:00 exactas.
    huella = int(((utc.dt.hour == 0) & (utc.dt.minute == 10)
                  & (utc.dt.second == 0)).sum())
    if huella > 20:
        fallas.append(f"transacciones a las 00:10:00 exactas: {huella} (esperado < 20)")

    # Clientes sin perfil: el escenario que v0.3 declaró "el que más importa"
    # y que el dataset original no tenía.
    sin_perfil = ~tx.customer_id.isin(cb.customer_id)
    _rango(fallas, "tx de clientes sin perfil", int(sin_perfil.sum()), 80, 180)

    m = tx[~sin_perfil].merge(cb, on="customer_id", suffixes=("", "_perfil"))

    # La moneda es de la cuenta, no del país donde ocurre la compra.
    discrepancia = int((m.currency != m.currency_perfil).sum())
    if discrepancia:
        fallas.append(f"moneda de tx distinta de la de la cuenta: {discrepancia}")

    ratio = m.amount.astype(float) / m.usual_amount_avg.astype(float)
    horas = m.usual_hours.str.split("-", expand=True).astype(int)
    utc_m = pd.to_datetime(m.timestamp, utc=True, format="ISO8601")

    # La ventana se evalúa en hora LOCAL. Si esto se hiciera en UTC, la
    # columna `timezone` sería decorativa.
    hora_local = [t.tz_convert(ZoneInfo(z)).hour for t, z in zip(utc_m, m.timezone)]
    fuera = pd.Series(
        [not _en_ventana(h, i, f) for h, i, f in zip(hora_local, horas[0], horas[1])]
    )

    def pais_ajeno(fila):
        habituales = [c for c in fila.usual_countries.split(";") if c]
        return fila.country not in habituales if habituales else True

    extranjero = m.apply(pais_ajeno, axis=1)
    disp_nuevo = m.device_id != m.usual_devices
    canal_nuevo = m.chanel != m.usual_channel

    # El corazón de esta etapa. En el dataset original las tres dimensiones
    # tenían precisión 1.0 porque no existía un solo caso benigno: la clase
    # que mide la precisión no existía, y cualquier métrica salía inflada.
    dimensiones = [
        ("país ≠ habitual", extranjero, extranjero & ~disp_nuevo),
        ("dispositivo ≠ habitual", disp_nuevo,
         disp_nuevo & m.device_id.str.startswith("D-777")),
        ("canal ≠ habitual", canal_nuevo, canal_nuevo & (ratio <= 2)),
        ("monto > 3x", ratio > 3, (ratio > 3) & ~fuera),
    ]
    for etiqueta, activa, benigna in dimensiones:
        total, buenos = int(activa.sum()), int(benigna.sum())
        if total == 0:
            fallas.append(f"{etiqueta}: ninguna transacción la activa")
            continue
        fraccion = buenos / total
        if fraccion < FRACCION_BENIGNA_MINIMA:
            fallas.append(
                f"{etiqueta} sigue siendo predictor casi perfecto: "
                f"{buenos}/{total} benignas ({fraccion:.0%}, "
                f"esperado ≥ {FRACCION_BENIGNA_MINIMA:.0%})"
            )

    # El conteo de positivos por política se verifica en check_ground_truth,
    # donde lo produce la regla misma en vez de una aproximación.
    return fallas


# Las diez políticas dentro del alcance implementado. FP-10 (alerta externa)
# queda fuera: su evidencia es búsqueda web real, no reproducible.
POLITICAS_EN_ALCANCE = [
    "FP-01", "FP-02", "FP-03", "FP-04", "FP-05",
    "FP-06", "FP-07", "FP-08", "FP-09", "FP-11",
]

DECISIONES = {"APPROVE", "CHALLENGE", "BLOCK", "ESCALATE_TO_HUMAN"}


def check_ground_truth(gt: pd.DataFrame, tx: pd.DataFrame) -> list[str]:
    fallas: list[str] = []

    if len(gt) != len(tx):
        fallas.append(f"etiquetas: {len(gt)} para {len(tx)} transacciones")
    if set(gt.transaction_id) != set(tx.transaction_id):
        fallas.append("las claves de ground_truth no coinciden con transactions")

    ajenas = set(gt.expected_decision) - DECISIONES
    if ajenas:
        fallas.append(f"decisiones fuera del enum: {sorted(ajenas)}")

    conteo = (gt.expected_policies.str.split(";").explode()
              .replace("", pd.NA).dropna().value_counts().to_dict())

    # Cada política necesita masa suficiente para que su F1 signifique algo.
    # Por debajo de ~30 positivos un solo error mueve la métrica varios puntos.
    for pol in POLITICAS_EN_ALCANCE:
        _minimo(fallas, f"positivos de {pol}", conteo.get(pol, 0), 30)

    if "FP-10" in conteo:
        fallas.append("FP-10 aparece en el ground truth (está fuera de alcance)")

    # La población negativa es lo que hace medible la precisión.
    aprobadas = int((gt.expected_decision == "APPROVE").sum())
    if aprobadas < len(gt) * 0.7:
        fallas.append(f"transacciones APPROVE: {aprobadas} (esperado > 70%)")

    # Cada grupo tiene al menos dos miembros y exactamente una transacción que
    # lo cierra: es la única que lleva etiqueta, porque cuando llegó la primera
    # el patrón todavía no existía.
    miembros = (gt[gt.fraud_group_id != ""]
                .assign(gid=lambda d: d.fraud_group_id.str.split(";"))
                .explode("gid"))
    if len(miembros):
        tamanos = miembros.groupby("gid").size()
        chicos = int((tamanos < 2).sum())
        if chicos:
            fallas.append(f"grupos con menos de 2 miembros: {chicos}")
        cierres = miembros[miembros.is_closing == "true"].groupby("gid").size()
        sin_cierre = len(tamanos) - len(cierres)
        if sin_cierre:
            fallas.append(f"grupos sin transacción de cierre: {sin_cierre}")
    else:
        fallas.append("ningún grupo de secuencia detectado")

    return fallas


def main() -> int:
    ruta_cb = DATA_DIR / "customer_behaviors.csv"
    ruta_tx = DATA_DIR / "transactions.csv"
    ruta_gt = DATA_DIR / "ground_truth.csv"
    for ruta in (ruta_cb, ruta_tx):
        if not ruta.exists():
            print(f"FALTA {ruta} — corre antes scripts/generate_data.py")
            return 1

    # `keep_default_na=False` es obligatorio: sin él pandas convierte las
    # celdas vacías en NaN y las comparaciones con "" fallan en silencio.
    cb = pd.read_csv(ruta_cb, dtype=str, keep_default_na=False)
    tx = pd.read_csv(ruta_tx, dtype=str, keep_default_na=False)

    fallas = check_profiles(cb) + check_transactions(tx, cb)

    if ruta_gt.exists():
        gt = pd.read_csv(ruta_gt, dtype=str, keep_default_na=False)
        fallas += check_ground_truth(gt, tx)
        print(f"perfiles: {len(cb)} | transacciones: {len(tx)} | etiquetas: {len(gt)}")
    else:
        print(f"perfiles: {len(cb)} | transacciones: {len(tx)} | etiquetas: (aún no)")

    if fallas:
        print(f"\n{len(fallas)} falla(s):")
        for f in fallas:
            print(f"  - {f}")
        return 1

    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
