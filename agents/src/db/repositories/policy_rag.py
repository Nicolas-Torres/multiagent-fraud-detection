"""Recuperación vectorial del corpus de políticas (RAG).

El invariante de este módulo: **toda recuperación pasa por acá** y devuelve
chunks con su distancia. El nodo Internal Policy RAG consume esto para construir
las citas internas.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import PolicyChunk


async def buscar_politicas(
    session: AsyncSession,
    embedding: list[float],
    *,
    top_k: int = 5,
    min_score: float | None = None,
) -> list[tuple[PolicyChunk, float]]:
    """Recupera los `top_k` chunks más cercanos por similitud coseno.

    Devuelve `(chunk, score)` con `score` en `[0, 1]` (1 = máximo parecido),
    usando `<=>`. `min_score` filtra ruido: chunks irrelevantes no respaldan
    un veredicto (contrato §2.5: "la cita autoriza el veredicto").
    """
    # El operador `<=>` devuelve distancia coseno: 1 - coseno. La convertimos a
    # score de similitud con `1 - dist` y la evaluamos en Python para poder
    # filtrar por `min_score` sin SQL dinámico.
    distancia = PolicyChunk.embedding.cosine_distance(embedding)
    stmt = (
        select(PolicyChunk, distancia.label("dist"))
        .order_by(distancia)
        .limit(top_k)
    )
    filas = await session.execute(stmt)
    resultados = []
    for chunk, dist in filas:
        score = 1.0 - float(dist)
        if min_score is not None and score < min_score:
            continue
        resultados.append((chunk, score))
    return resultados
