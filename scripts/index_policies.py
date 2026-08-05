"""Construye el índice vectorial de las políticas en `policy_chunks`. ADR-0012.

    uv run python scripts/index_policies.py           # indexa lo que falta
    uv run python scripts/index_policies.py --force   # re-embebe todo
    uv run python scripts/index_policies.py --fake    # sin red, para verificar idempotencia
    uv run python scripts/index_policies.py --dry-run # muestra qué haría

Lee el catálogo **de Postgres**, no de los JSON: los chunks tienen FK compuesta a
`fraud_policies(policy_id, version)`, así que sólo se indexa lo que está
publicado. Corre `seed.py` antes.

## Idempotencia, y por qué saltear no es una optimización

Un chunk ya presente bajo el mismo `index_version` y con el mismo `content` **no
se vuelve a embeber**. Parece un ahorro de cuota y es una decisión de fondo: el
embedding es función de (modelo, plantilla, dimensión, contenido), y los cuatro
están sellados en la versión. Si algo de eso cambia, cambia la versión y las
filas son otras. Si no cambió nada, volver a llamar sólo abre la puerta a que el
proveedor devuelva un vector distinto para el mismo texto —el riesgo que ADR-0012
existe para cerrar— y a que el índice deje de ser reproducible sin que nada lo
avise.

`--force` está para el caso en que uno *sabe* que quiere re-embeber sin cambiar
de versión. Es explícito por la misma razón que `--reset` en el seed.

## Qué se indexa

Todas las políticas del catálogo, sin filtrar por estado. Una política `PENDING`
o `EXCLUDED` nunca aparece en `matched_policies`, así que el descubrimiento es su
única vía de llegar a un caso: filtrarlas dejaría fuera justo las que dependen
del índice para existir.
"""

import argparse
import sys

from sqlalchemy import create_engine, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from multiagent_fraud_detection.config.settings import settings
from multiagent_fraud_detection.db.models import PolicyChunk
from multiagent_fraud_detection.db.repositories.policy_catalog import DbCatalogSource
from multiagent_fraud_detection.domain.catalog import build_catalog
from multiagent_fraud_detection.retrieval.chunking import chunk_all, whole_document
from multiagent_fraud_detection.retrieval.embeddings import (
    FAKE_INDEX_VERSION,
    INDEX_VERSION,
    Embedder,
    FakeEmbedder,
    GeminiEmbedder,
    format_document,
)


def existentes(session: Session, index_version: str) -> dict[str, str]:
    """`chunk_id` → `content` de lo ya indexado bajo esta versión."""
    filas = session.execute(
        select(PolicyChunk.chunk_id, PolicyChunk.content).where(
            PolicyChunk.index_version == index_version
        )
    ).all()
    return {chunk_id: content for chunk_id, content in filas}


def indexar(
    session: Session,
    embedder: Embedder,
    index_version: str,
    *,
    force: bool = False,
    dry_run: bool = False,
) -> tuple[int, int]:
    """Devuelve (indexados, salteados)."""
    catalogo = build_catalog(DbCatalogSource().fetch_with(session))
    chunks = chunk_all(catalogo.policies, split=whole_document)

    ya = existentes(session, index_version)
    indexados = salteados = 0

    for chunk in chunks:
        vigente = ya.get(chunk.chunk_id)
        if not force and vigente == chunk.content:
            salteados += 1
            continue

        motivo = (
            "nuevo" if vigente is None
            else "texto cambiado" if vigente != chunk.content
            else "--force"
        )
        print(f"  {chunk.chunk_id:24s} {motivo}")

        if dry_run:
            indexados += 1
            continue

        vector = embedder.embed(format_document(chunk.content))

        stmt = pg_insert(PolicyChunk).values(
            index_version=index_version,
            chunk_id=chunk.chunk_id,
            policy_id=chunk.policy_id,
            source_version=chunk.source_version,
            ordinal=chunk.ordinal,
            content=chunk.content,
            embedding=vector,
        )
        session.execute(
            stmt.on_conflict_do_update(
                index_elements=["index_version", "chunk_id"],
                set_={
                    "policy_id": stmt.excluded.policy_id,
                    "source_version": stmt.excluded.source_version,
                    "ordinal": stmt.excluded.ordinal,
                    "content": stmt.excluded.content,
                    "embedding": stmt.excluded.embedding,
                    "embedded_at": func.now(),
                },
            )
        )
        indexados += 1

    return indexados, salteados


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
            indexados, salteados = indexar(
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

            total = session.scalar(
                select(func.count())
                .select_from(PolicyChunk)
                .where(PolicyChunk.index_version == index_version)
            )
    finally:
        engine.dispose()

    print(f"\n{indexados} indexados · {salteados} sin cambios · {total} filas en el índice")
    return 0


if __name__ == "__main__":
    sys.exit(main())
