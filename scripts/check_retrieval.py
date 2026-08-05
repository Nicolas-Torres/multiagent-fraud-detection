"""Ablación de el bloque de descubrimiento. Paso 5 de la etapa.

    uv run python scripts/check_retrieval.py            # la corrida completa
    uv run python scripts/check_retrieval.py --dry-run  # cuántas llamadas costaría
    uv run python scripts/check_retrieval.py --k 1 3 5   # la curva que se elija
    uv run python scripts/check_retrieval.py --min-recall 0.90   # como gate

Corre la **búsqueda vectorial sola** sobre las 7 000 transacciones y la compara
con `expected_policies`. Mide lo que pasaría si `citations_internal` saliera
únicamente del índice, que es la alternativa que ADR-0011 descartó.

## Por qué esto no es un gate de calidad del RAG

el bloque de autorización tiene recall 1.0 **por construcción**: no consulta el
índice, resuelve por identidad contra el catálogo. Así que este número no mide si
el sistema cita bien —eso ya está garantizado— sino **cuánto valdría el índice si
fuera la única fuente**. Si da 0.93, ese 7% es la proporción de veredictos que
habrían citado mal, y es la evidencia empírica de ADR-0011.

`expected_policies` sirve para esto y no para más: dice qué citas son
**obligatorias**, y no dice nada sobre cuáles están *permitidas*. Define recall
con precisión total y precision en absoluto. Por eso acá no hay precision: una
política recuperada que no disparó no es un falso positivo, es descubrimiento.

## Por qué se mide una curva y no un k

Con once documentos, `k=5` es el 45% del corpus: un recuperador al azar sacaría
~0.455 de recall sin entender nada. Un solo número alto no distingue un índice
bueno de un corpus chico. La curva sí: `k=1` obliga a acertar la política exacta,
y la caída entre `k=1` y `k=5` es donde vive la información.

El **azar** se imprime al lado de cada k por eso mismo — es el piso contra el que
hay que leer el resultado, no el cero.

## El sesgo que hay que publicar con el número

La query se arma con las `description` de los predicados, y con un chunk por
documento el índice contiene casi ese mismo texto. Buscar la política que produjo
la señal es casi buscar el texto por sí mismo. **El recall va a salir alto por
construcción, no por mérito**, y el informe tiene que decirlo — igual que dice que
el corpus de once líneas sobredimensiona el bloque de identidad.

## Costo

Una llamada al proveedor por **combinación distinta de códigos de señal**, no por
transacción: ése fue el motivo de armar la query desde los códigos y no desde las
descripciones. `--dry-run` dice cuántas son antes de gastarlas.
"""

import argparse
import sys
from collections import defaultdict

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from multiagent_fraud_detection.config.settings import settings
from multiagent_fraud_detection.db.repositories.policy_catalog import DbCatalogSource
from multiagent_fraud_detection.db.models import PolicyChunk
from multiagent_fraud_detection.domain.catalog import build_catalog
from multiagent_fraud_detection.enums import DecisionType
from multiagent_fraud_detection.retrieval.embeddings import (
    INDEX_VERSION,
    GeminiEmbedder,
    format_query,
)
from multiagent_fraud_detection.graph.nodes import RAG_TOP_K
from multiagent_fraud_detection.retrieval.query import (
    QueryCache,
    build_query,
    query_codes,
)

from _dataset import BLACKLIST, leer_ground_truth, leer_perfiles, leer_transacciones
from check_policies import evaluar_todo

KS_POR_DEFECTO = (1, 3, 5, 10)


def combinaciones(obtenido: dict) -> dict[tuple[str, ...], list[str]]:
    """`combinación de códigos` → transacciones que la producen.

    Agrupar antes de embeber es lo que convierte 7 000 llamadas en decenas.
    """
    grupos: dict[tuple[str, ...], list[str]] = defaultdict(list)
    for tid, (_politicas, _decision, señales) in obtenido.items():
        grupos[query_codes(s.code for s in señales)].append(tid)
    return grupos


def recuperar(
    session: Session, embedder, cache: QueryCache, vocabulario, codigos, k: int
) -> list[str]:
    """`policy_id` recuperados para una combinación, en orden de cercanía."""
    if not codigos:
        # Sin códigos utilizables no hay query. Cuenta como recall 0 si la
        # transacción tenía políticas esperadas, y es información: hay casos
        # donde el índice no puede aportar nada por construcción.
        return []

    vector = cache.get(codigos)
    if vector is None:
        vector = embedder.embed(format_query(build_query(codigos, vocabulario)))
        cache.put(codigos, vector)

    # La misma consulta que `search_similar`, en version sincronica: este script
    # mide, no corre el grafo, y arrastrar un event loop para 7 000 lecturas
    # secuenciales no compra nada. El filtro por `index_version` se repite aca
    # con el mismo cuidado: es invariante de correccion, no optimizacion.
    distancia = PolicyChunk.embedding.cosine_distance(vector)
    filas = session.execute(
        select(PolicyChunk.policy_id)
        .where(PolicyChunk.index_version == INDEX_VERSION)
        .order_by(distancia)
        .limit(k)
    ).all()

    return [f.policy_id for f in filas]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--k",
        type=int,
        nargs="+",
        default=list(KS_POR_DEFECTO),
        help="topes de recuperación a medir; se recupera una vez al mayor",
    )
    ap.add_argument("--dry-run", action="store_true", help="solo el costo en llamadas")
    ap.add_argument(
        "--min-recall",
        type=float,
        default=None,
        help="si se pasa, retorna 1 cuando el recall macro queda por debajo",
    )
    args = ap.parse_args()
    # `RAG_TOP_K` entra siempre: es el k con el que el nodo recupera de verdad, y
    # la conclusion del reporte tiene que hablar del sistema que corre, no del k
    # mas grande que alguien haya pedido medir.
    ks = sorted({k for k in args.k if k > 0} | {RAG_TOP_K})
    k_max = max(ks)

    engine = create_engine(settings.database_url)
    try:
        with Session(engine) as session:
            catalogo = build_catalog(DbCatalogSource().fetch_with(session))
            vocabulario = {}
            for politica in catalogo.policies:
                for paso in politica.condition:
                    vocabulario.setdefault(
                        paso.predicate.signal_code(**paso.params),
                        paso.predicate.description,
                    )

            print(f"catálogo {catalogo.version} · {len(vocabulario)} códigos · "
                  f"k={ks} · {len(catalogo.policies)} documentos")

            perfiles = {p.customer_id: p for p in leer_perfiles()}
            transacciones = leer_transacciones()
            blacklist = frozenset(m.merchant_id for m in BLACKLIST)
            esperado = leer_ground_truth()

            obtenido = evaluar_todo(catalogo, perfiles, transacciones, blacklist)
            grupos = combinaciones(obtenido)

            print(f"{len(transacciones)} transacciones · "
                  f"{len(grupos)} combinaciones distintas de señales")
            print(f"llamadas al proveedor: {sum(1 for c in grupos if c)}")

            if args.dry_run:
                return 0

            # --- recuperación, una vez por combinación --------------------- #
            embedder = GeminiEmbedder()
            cache = QueryCache()
            por_combinacion: dict[tuple[str, ...], list[str]] = {}

            for i, codigos in enumerate(sorted(grupos), start=1):
                por_combinacion[codigos] = recuperar(
                    session, embedder, cache, vocabulario, codigos, k_max
                )
                if i % 10 == 0 or i == len(grupos):
                    print(f"  {i}/{len(grupos)} combinaciones recuperadas", end="\r")
            print()
    finally:
        engine.dispose()

    # --- medición ---------------------------------------------------------- #
    corpus = len(catalogo.policies)
    con_esperadas = 0
    sin_query = 0
    por_k: dict[int, dict[str, float]] = {}
    por_politica_ok = defaultdict(int)
    por_politica_total = defaultdict(int)
    rr: list[float] = []

    casos: list[tuple[set[str], list[str]]] = []

    for tid, esp in esperado.items():
        esperadas = set(esp["policies"])
        if not esperadas:
            continue

        con_esperadas += 1
        codigos = query_codes(s.code for s in obtenido[tid][2])
        recuperadas = por_combinacion.get(codigos, [])
        if not codigos:
            sin_query += 1

        casos.append((esperadas, recuperadas))

        for p in esperadas:
            por_politica_total[p] += 1
            # Al `k` operativo y no al mayor: esta tabla existe para localizar
            # donde el indice falla, y al k mas grande no falla nada por
            # construccion. Es el mismo error metodologico que la curva evita.
            if p in recuperadas[:RAG_TOP_K]:
                por_politica_ok[p] += 1

        posicion = next(
            (i for i, p in enumerate(recuperadas, start=1) if p in esperadas), None
        )
        rr.append(1 / posicion if posicion else 0.0)

    for k in ks:
        recalls = []
        aciertos = 0
        for esperadas, recuperadas in casos:
            top = set(recuperadas[:k])
            encontradas = esperadas & top
            recalls.append(len(encontradas) / len(esperadas))
            if encontradas:
                aciertos += 1
        por_k[k] = {
            "recall": sum(recalls) / len(recalls) if recalls else 0.0,
            "hit": aciertos / len(casos) if casos else 0.0,
            # Piso del azar: la probabilidad de que una politica esperada caiga
            # entre k documentos elegidos al azar de un corpus de `corpus`.
            "azar": min(1.0, k / corpus),
        }

    mrr = sum(rr) / len(rr) if rr else 0.0
    recall = por_k[RAG_TOP_K]["recall"]

    print(f"\ntransacciones con políticas esperadas: {con_esperadas}")
    print(f"  de ellas, sin query posible: {sin_query}")

    print(f"\n{'k':>3s}  {'recall':>7s} {'hit-rate':>9s} {'azar':>7s} {'sobre azar':>11s}")
    for k in ks:
        m = por_k[k]
        print(f"{k:3d}  {m['recall']:7.3f} {m['hit']:9.3f} {m['azar']:7.3f} "
              f"{m['recall'] - m['azar']:+11.3f}")

    print(f"\nMRR: {mrr:.3f}  (ranking, no pertenencia: es lo que k grande esconde)")

    print(f"\npor política (k={RAG_TOP_K}, el operativo):")
    for p in sorted(por_politica_total):
        total_p = por_politica_total[p]
        ok = por_politica_ok[p]
        print(f"  {p:7s} {ok:5d}/{total_p:5d}  recall {ok / total_p:.3f}")

    # --- lo que la etapa desbloqueó ---------------------------------------- #
    reparto = defaultdict(int)
    for esp in esperado.values():
        reparto[esp["decision"]] += 1

    escalan = reparto.get(DecisionType.ESCALATE_TO_HUMAN.value, 0)
    total = sum(reparto.values())

    print("\nveredictos que el catálogo prescribe:")
    for accion, n in sorted(reparto.items(), key=lambda kv: -kv[1]):
        print(f"  {accion:20s} {n:5d}  {n / total:6.1%}")

    print(
        f"\nantes de esta etapa escalaban {total}/{total} (100.0%) por falta de "
        f"respaldo interno;\nahora escalan {escalan}/{total} ({escalan / total:.1%}), "
        f"y sólo porque su política lo prescribe."
    )

    print(
        f"\nLectura (k={RAG_TOP_K}, el que usa el nodo): la autorización tiene "
        f"recall 1.0 por\nconstrucción. El {1 - recall:.1%} que el índice no "
        f"alcanza es la proporción de veredictos\nque habrían citado mal si "
        f"`citations_internal` saliera sólo de la búsqueda\nvectorial (ADR-0011). "
        f"Leer la curva, no un k: con {corpus} documentos, k={k_max}\nya supera "
        f"al azar por poco y deja de medir nada."
    )

    if args.min_recall is not None and recall < args.min_recall:
        print(f"\nFALLA: recall {recall:.3f} < mínimo {args.min_recall:.3f}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
