"""Construcción del índice vectorial. ADR-0012.

Biblioteca con dos entradas: `scripts/index_policies.py` para correrla a mano y
`scripts/seed.py` para el Job de post-deploy. La lógica vive acá y no en el
script porque el ADR pide que la indexación ocurra **dentro** del seed, y un
script que importa a otro script convierte al segundo en biblioteca sin decirlo.

## Idempotencia, y por qué saltear no es una optimización

Un chunk ya presente bajo el mismo `index_version` y con el mismo `content` **no
se vuelve a embeber**. Parece un ahorro de cuota y es una decisión de fondo: el
embedding es función de (modelo, plantilla, dimensión, contenido), y los cuatro
están sellados en la versión. Si algo de eso cambia, cambia la versión y las
filas son otras. Si no cambió nada, volver a llamar sólo abre la puerta a que el
proveedor devuelva un vector distinto para el mismo texto —el riesgo que ADR-0012
existe para cerrar— y a que el índice deje de ser reproducible sin que nada lo
avise.

`force=True` está para el caso en que uno *sabe* que quiere re-embeber sin
cambiar de versión. Es explícito por la misma razón que `--reset` en el seed.

## Sincrónico

Usa `DbCatalogSource`, que es sincrónico porque el catálogo se lee una vez por
proceso. Indexar tampoco es concurrente: once llamadas en serie a un proveedor
externo no ganan nada con un event loop.
"""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from multiagent_fraud_detection.db.models import PolicyChunk
from multiagent_fraud_detection.db.repositories.policy_catalog import DbCatalogSource
from multiagent_fraud_detection.domain.catalog import build_catalog
from multiagent_fraud_detection.retrieval.chunking import Splitter, chunk_all, whole_document
from multiagent_fraud_detection.retrieval.embeddings import Embedder, format_document


def indexed_contents(session: Session, index_version: str) -> dict[str, str]:
    """`chunk_id` → `content` de lo ya indexado bajo esta versión."""
    filas = session.execute(
        select(PolicyChunk.chunk_id, PolicyChunk.content).where(
            PolicyChunk.index_version == index_version
        )
    ).all()
    return {chunk_id: content for chunk_id, content in filas}


def index_catalog(
    session: Session,
    embedder: Embedder,
    index_version: str,
    *,
    force: bool = False,
    dry_run: bool = False,
    split: Splitter = whole_document,
    report: Callable[[str], None] = print,
) -> tuple[int, int]:
    """Indexa lo que falta. Devuelve `(indexados, salteados)`.

    No commitea: el llamador decide la transacción. El seed lo necesita así para
    que el catálogo y su índice entren o no entren juntos.
    """
    catalogo = build_catalog(DbCatalogSource().fetch_with(session))
    chunks = chunk_all(catalogo.policies, split=split)

    ya = indexed_contents(session, index_version)
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
        report(f"  {chunk.chunk_id:24s} {motivo}")

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


def index_size(session: Session, index_version: str) -> int:
    return session.scalar(
        select(func.count())
        .select_from(PolicyChunk)
        .where(PolicyChunk.index_version == index_version)
    ) or 0
