"""Corre el motor determinístico sobre el dataset y lo compara con el ground truth.

    uv run python scripts/check_policies.py                →  resumen + código de salida
    uv run python scripts/check_policies.py --detalle       →  además, cada discrepancia
    uv run python scripts/check_policies.py --source=db     →  el catálogo desde Postgres

**Sin red, sin LLM.** Las 7 000 transacciones en segundos. Por eso es un gate de CI
y no un smoke test: corre en cada push, no cuando alguien se acuerda.

## Las dos fuentes del catálogo

`--source=file` (default) lee los JSON versionados: **sin base de datos**, que es
lo que permite correrlo en CI sin Postgres levantado. `--source=db` lee las tablas
de la fase 3 de ADR-0007.

El mismo gate contra las dos fuentes es la prueba de la migración del catálogo a
Postgres: si mudarlo cambió una sola de las 7 000 filas, el número lo dice. No
hace falta escribir una prueba nueva para la migración de datos — ya existe y es
más fuerte que cualquiera que se escribiera a propósito.

## Qué prueba, y por qué eso vale

`build_ground_truth.py` y el motor son **dos implementaciones independientes de
las mismas once políticas**: una escrita a mano con pandas, la otra interpretando
las vinculaciones del catálogo. Que coincidan en 7 000 filas es evidencia fuerte
de que ambas están bien; que discrepen es un hallazgo, no un fallo de tipeo.

Comparten sólo los parámetros que ninguna norma menciona —la tabla FX, los
promedios por segmento, la precedencia—, porque un desacuerdo sobre el factor del
sol no probaría nada: sería ruido con forma de hallazgo (ADR-0007).

## Qué NO prueba

Que el sistema decida bien. En esta etapa `citations_internal` está vacío —el RAG
no existe— así que todo veredicto autónomo es imposible y el grafo completo
mandaría todo a `ESCALATE_TO_HUMAN`. Acá se mide la **capa de reglas**: qué
políticas disparan y qué acción prescriben. El F1 de la decisión del sistema llega
con el RAG.

Tampoco prueba las consultas: acá el historial se arma en memoria. Un bug de
`as_of` en el repositorio sólo lo atrapa el smoke contra la base sembrada.
"""

import argparse
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from multiagent_fraud_detection.domain.catalog import (
    CatalogSource,
    FileCatalogSource,
    Owner,
    build_catalog,
)
from multiagent_fraud_detection.domain.engine import evaluate, prescribed_action
from multiagent_fraud_detection.domain.predicates import EvalContext
from multiagent_fraud_detection.enums import IndicatorType

from _dataset import (
    BLACKLIST,
    DATA_DIR,
    leer_ground_truth,
    leer_perfiles,
    leer_transacciones,
)

# La misma ventana que usa el repositorio de historial: acá se replica en memoria
# para que el gate mida lo mismo que va a correr contra Postgres.
WINDOW = timedelta(hours=26)

POLICIES = DATA_DIR / "policies"


def elegir_fuente(nombre: str) -> CatalogSource:
    """Construye la fuente pedida.

    El import de `DbCatalogSource` es perezoso a propósito: el gate offline no
    debería poder fallar por un error de importación de la capa de base de datos,
    que es lo único que no necesita.
    """
    if nombre == "db":
        from multiagent_fraud_detection.db.repositories.policy_catalog import (
            DbCatalogSource,
        )

        return DbCatalogSource()

    return FileCatalogSource(
        POLICIES / "fraud_policies_2025.1.json",
        POLICIES / "policy_bindings_2025.1.json",
    )


@dataclass(frozen=True, slots=True)
class _IndicadorSintetico:
    """Un indicador fabricado por el gate. Lleva su origen en la URL a propósito.

    El predicado sólo mira `observed_at` y `source_url`, así que no hace falta
    importar `Indicator` de `db/repositories/` —y no conviene: eso arrastraría la
    capa de base al gate que corre sin Postgres—.
    """

    observed_at: datetime
    retrieved_at: datetime
    source_url: str = "https://synthetic.invalid/check_policies/corpus-saturado"
    summary: str = "Indicador sintetico del gate (no es dato real)"


def corpus_saturado(transacciones) -> dict:
    """Un indicador por emisor del dataset, fechado **hoy**. El peor caso posible.

    ADR-0015 afirma que FP-10 no puede disparar sobre el dataset *aunque la tabla
    esté llena*: las 7 000 transacciones son de diciembre de 2025 y la ventana de
    24 h se resuelve *as-of* contra el `timestamp` del cargo, así que cualquier
    indicador capturado hoy queda a ocho meses.

    Este corpus lo **demuestra** en vez de suponerlo. Con la tabla vacía —que es
    como está hoy el snapshot real— la afirmación sería verdadera por
    configuración, y una invariante que depende de que alguien recuerde el
    desfase de fechas no es una invariante. Si algún día el dataset se regenerara
    con fechas actuales, este gate se pondría rojo el mismo día.
    """
    hoy = datetime.now(timezone.utc)
    ahora = (_IndicadorSintetico(observed_at=hoy, retrieved_at=hoy),)
    return {
        (IndicatorType.ISSUER, t.issuer_bank): ahora
        for t in transacciones
        if t.issuer_bank
    }


def evaluar_todo(catalog, perfiles, transacciones, blacklist, indicadores):
    """Recorre el dataset en orden cronológico, acumulando historial.

    El orden importa y el acumulado también: una transacción se juzga con lo que
    existía **antes** de ella. Es el invariante *as-of* reproducido en memoria —el
    mismo que el repositorio hace cumplir con `timestamp <= :as_of`—.
    """
    por_cliente = defaultdict(list)
    por_dispositivo = defaultdict(list)
    salida = {}

    for tx in sorted(transacciones, key=lambda t: t.timestamp):
        hist_cli = [
            t for t in por_cliente[tx.customer_id] if tx.timestamp - t.timestamp < WINDOW
        ]
        hist_dev = [
            t for t in por_dispositivo[tx.device_id] if tx.timestamp - t.timestamp < WINDOW
        ]

        ctx = EvalContext(
            transaction=tx,
            profile=perfiles.get(tx.customer_id),
            history_customer=tuple(hist_cli),
            history_device=tuple(hist_dev),
            blacklist=blacklist,
            indicators=indicadores,
        )

        # Los tres agentes por separado y luego consolidados, igual que el grafo:
        # corren en paralelo en el superstep 0 y Evidence Aggregation une.
        ev = (
            evaluate(catalog, Owner.CONTEXT, ctx)
            .merge(evaluate(catalog, Owner.BEHAVIORAL, ctx))
            .merge(evaluate(catalog, Owner.THREAT_INTEL, ctx))
        )

        salida[tx.transaction_id] = (
            sorted(ev.matched_policies),
            prescribed_action(catalog, ev.matched_policies).value,
            ev.signals,
        )

        por_cliente[tx.customer_id].append(tx)
        por_dispositivo[tx.device_id].append(tx)

    return salida


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--detalle", action="store_true", help="lista cada discrepancia")
    ap.add_argument(
        "--source",
        choices=("file", "db"),
        default="file",
        help="de dónde sale el catálogo (default: file, sin base de datos)",
    )
    args = ap.parse_args()

    catalog = build_catalog(elegir_fuente(args.source).fetch())
    print(f"fuente {args.source} · catálogo {catalog.version} · {catalog.health}")

    if catalog.health["stale"]:
        print("  aviso: hay vinculaciones obsoletas; esas políticas no se evalúan")

    perfiles = {p.customer_id: p for p in leer_perfiles()}
    transacciones = leer_transacciones()
    blacklist = frozenset(m.merchant_id for m in BLACKLIST)
    indicadores = corpus_saturado(transacciones)
    esperado = leer_ground_truth()

    obtenido = evaluar_todo(
        catalog, perfiles, transacciones, blacklist, indicadores
    )

    # --- comparación --------------------------------------------------------
    tp = defaultdict(int)
    fp = defaultdict(int)
    fn = defaultdict(int)
    señales = defaultdict(int)
    discrepancias = []
    decision_mal = 0

    for tid, esp in esperado.items():
        got_pol, got_dec, got_sig = obtenido[tid]
        for s in got_sig:
            señales[s.code] += 1

        for p in set(got_pol) & set(esp["policies"]):
            tp[p] += 1
        for p in set(got_pol) - set(esp["policies"]):
            fp[p] += 1
        for p in set(esp["policies"]) - set(got_pol):
            fn[p] += 1

        if got_pol != esp["policies"]:
            discrepancias.append((tid, esp["policies"], got_pol))
        if got_dec != esp["decision"]:
            decision_mal += 1

    # --- reporte ------------------------------------------------------------
    print(f"\ntransacciones evaluadas : {len(esperado)}")
    print(f"discrepancias de política: {len(discrepancias)}")
    print(f"discrepancias de decisión: {decision_mal}")

    print("\npor política:")
    print(f"  {'ID':7s} {'TP':>5s} {'FP':>5s} {'FN':>5s}  {'prec':>6s} {'rec':>6s} {'F1':>6s}")
    for p in sorted(set(tp) | set(fp) | set(fn)):
        prec = tp[p] / (tp[p] + fp[p]) if tp[p] + fp[p] else 0.0
        rec = tp[p] / (tp[p] + fn[p]) if tp[p] + fn[p] else 0.0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        print(f"  {p:7s} {tp[p]:5d} {fp[p]:5d} {fn[p]:5d}  {prec:6.3f} {rec:6.3f} {f1:6.3f}")

    print("\nseñales emitidas:")
    for code, n in sorted(señales.items(), key=lambda kv: -kv[1]):
        print(f"  {code:26s} {n:5d}")

    # --- la invariante de FP-10, afirmada y no supuesta ---------------------
    #
    # FP-10 no tiene ground truth —el dataset no la contempla y no se regenera
    # (ADR-0015)—, así que su ausencia de la tabla de arriba no prueba nada por
    # sí sola. Lo que se afirma acá es más fuerte: con un indicador activo para
    # **todos** los emisores, fechado hoy, sigue sin disparar.
    fp10_disparo = sorted(
        tid for tid, (pol, _, _) in obtenido.items() if "FP-10" in pol
    )
    print(
        f"\nFP-10 · activa, sin ground truth · corpus saturado: "
        f"{len(indicadores)} emisores fechados hoy"
    )
    if fp10_disparo:
        print(f"  FALLA: disparó en {len(fp10_disparo)} transacciones "
              f"(p. ej. {fp10_disparo[0]})")
    else:
        print("  no disparó: el dataset es de diciembre de 2025 y la ventana de "
              "24 h se resuelve as-of contra el cargo")

    if args.detalle:
        for tid, esp, got in discrepancias:
            print(f"  {tid}: esperado={esp} obtenido={got}")

    if discrepancias or decision_mal or fp10_disparo:
        print("\nFALLA: el motor no reproduce el ground truth")
        return 1

    print("\nOK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
