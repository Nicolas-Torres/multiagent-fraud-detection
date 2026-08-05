"""Construye el índice vectorial de las políticas en `policy_chunks`. ADR-0012.

    uv run python scripts/index_policies.py           # indexa lo que falta
    uv run python scripts/index_policies.py --force   # re-embebe todo
    uv run python scripts/index_policies.py --fake    # sin red, para verificar idempotencia
    uv run python scripts/index_policies.py --dry-run # muestra qué haría

Lee el catálogo **de Postgres**, no de los JSON: los chunks tienen FK compuesta a
`fraud_policies(policy_id, version)`, así que sólo se indexa lo que está
publicado. Corre `seed.py` antes.

La lógica vive en `retrieval/indexing.py`; esto es la entrada de línea de
comandos. El seed usa la misma función, que es lo que pide ADR-0012 §1: la
indexación ocurre dentro del Job de seed, no como un cuarto modo de arranque.

## Qué se indexa

Todas las políticas del catálogo, sin filtrar por estado. Una política `PENDING`
o `EXCLUDED` nunca aparece en `matched_policies`, así que el descubrimiento es su
única vía de llegar a un caso: filtrarlas dejaría fuera justo las que dependen
del índice para existir.
"""

import argparse
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from multiagent_fraud_detection.config.settings import settings
from multiagent_fraud_detection.retrieval.embeddings import (
    FAKE_INDEX_VERSION,
    INDEX_VERSION,
    Embedder,
    FakeEmbedder,
    GeminiEmbedder,
)
from multiagent_fraud_detection.retrieval.indexing import index_catalog, index_size


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--force", action="store_true", help="re-embebe aunque nada haya cambiado")
    ap.add_argument(
        "--fake",
        action="store_true",
        help="vectores deterministas sin red, bajo un `index_version` propio",
    )
    ap.add_argument("--dry-run", action="store_true", help="no escribe ni llama al proveedor")
    args = ap.parse_args()

    embedder: Embedder = FakeEmbedder() if args.fake else GeminiEmbedder()
    index_version = FAKE_INDEX_VERSION if args.fake else INDEX_VERSION

    print(f"índice {index_version}")
    if args.fake:
        print("  --fake: vectores sin significado, versión aparte; no sirven para buscar")

    engine = create_engine(settings.database_url)
    try:
        with Session(engine) as session:
            indexados, salteados = index_catalog(
                session,
                embedder,
                index_version,
                force=args.force,
                dry_run=args.dry_run,
            )

            if args.dry_run:
                session.rollback()
                print(f"\n--dry-run: {indexados} se indexarían, {salteados} sin cambios")
                return 0

            # Un solo commit, igual que el seed: un índice a medias es peor que
            # ninguno, porque las búsquedas funcionan y devuelven de menos.
            session.commit()
            total = index_size(session, index_version)
    finally:
        engine.dispose()

    print(f"\n{indexados} indexados · {salteados} sin cambios · {total} filas en el índice")
    return 0


if __name__ == "__main__":
    sys.exit(main())
