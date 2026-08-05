"""Búsqueda vectorial sobre `policy_chunks`. ADR-0012 §6.

## Una sola función de búsqueda, y el filtro adentro

No hay poda de generaciones viejas: el índice acumula, y un `fake:1536:doc:1`
puede convivir con el vigente. Por eso

> `WHERE index_version = <vigente>` **no es un filtro, es un invariante de
> corrección**.

Sin él la consulta mezcla generaciones y devuelve vecinos calculados con otro
modelo —o directamente sin significado—. No falla, no lanza, no deja huella:
devuelve resultados plausibles y peores. Es la misma familia de fallo silencioso
que ADR-0011 cierra del lado de la citación y ADR-0007 del lado de la evaluación.

La defensa no es recordarlo en cada llamador: es que **no exista una forma de
consultar sin el filtro**. `index_version` tiene default —el vigente, que lo dice
el código— y no admite `None`. Se puede elegir otra generación, que es lo que
hace comparable un índice candidato; no se puede consultar todas.

> Corolario para quien escriba pruebas: una fila se identifica por
> `(index_version, chunk_id)`. El `chunk_id` es **idéntico** entre generaciones
> por diseño, así que comparar conjuntos de `chunk_id` no prueba nada sobre el
> filtro. Lo que discrimina es el conteo y la distancia.

## Por qué es asincrónico

A diferencia de `policy_catalog.py`, que se lee una vez por proceso, esto corre
**por caso** dentro del grafo. Va sobre la sesión async del nodo.

## Distancia coseno

`<=>` de pgvector. Coseno y no L2 porque los vectores están normalizados —el
modelo lo hace solo para dimensiones truncadas— y lo que importa es la dirección,
no la magnitud. Menor distancia es mayor parecido: el orden es ascendente.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import distinct, select
from sqlalchemy.ext.asyncio import AsyncSession

from multiagent_fraud_detection.db.models import FraudPolicy, PolicyChunk
from multiagent_fraud_detection.retrieval.embeddings import INDEX_VERSION


@dataclass(frozen=True, slots=True)
class ChunkMatch:
    """Un fragmento recuperado, con su distancia.

    **`ChunkMatch` y no `RetrievedChunk`**: ese nombre ya lo usa el estado del
    grafo para el objeto en vuelo, que es un modelo Pydantic con `score` y hereda
    de `InternalCitation`. Dos clases con el mismo nombre y forma parecida en el
    mismo proyecto son una trampa para la próxima persona que lea un import.

    Es un objeto plano y no un `PolicyChunk`: el vector de 1536 floats no tiene
    nada que hacer viajando al grafo, y devolver la entidad ORM ataría los nodos
    a una sesión abierta.
    """

    chunk_id: str
    policy_id: str
    source_version: str
    content: str
    distance: float

    @property
    def score(self) -> float:
        """Parecido en `[0, 1]`, que es lo que el estado del grafo espera.

        Con vectores normalizados la distancia coseno vive en `[0, 2]`, pero los
        embeddings de texto rara vez son opuestos: en la práctica queda en
        `[0, 1]` y se acota para que un caso extremo no produzca un score
        negativo en la frontera.
        """
        return max(0.0, 1.0 - self.distance)


async def search_similar(
    session: AsyncSession,
    query_vector: Sequence[float],
    *,
    limit: int = 5,
    index_version: str = INDEX_VERSION,
) -> tuple[ChunkMatch, ...]:
    """Los `limit` fragmentos más parecidos, dentro de **una** generación.

    `index_version` es argumento con default y no opcional a propósito: elegir
    otra generación es un uso previsto —comparar un índice candidato contra el
    vigente—, consultar sin generación no lo es.
    """
    distancia = PolicyChunk.embedding.cosine_distance(query_vector)

    filas = await session.execute(
        select(
            PolicyChunk.chunk_id,
            PolicyChunk.policy_id,
            PolicyChunk.source_version,
            PolicyChunk.content,
            distancia.label("distance"),
        )
        .where(PolicyChunk.index_version == index_version)
        .order_by(distancia)
        .limit(limit)
    )

    return tuple(
        ChunkMatch(
            chunk_id=f.chunk_id,
            policy_id=f.policy_id,
            source_version=f.source_version,
            content=f.content,
            distance=float(f.distance),
        )
        for f in filas
    )


async def unindexed_policies(
    session: AsyncSession, *, index_version: str = INDEX_VERSION
) -> tuple[str, ...]:
    """Políticas publicadas que no tienen ningún chunk en esta generación.

    **Tercera métrica operativa del entregable 6**, junto a *pendientes de
    vinculación* y *vinculaciones obsoletas*. Las tres son la misma clase de cosa:
    desincronizaciones entre artefactos con dueños distintos.

    Ésta en particular describe un estado legítimo y silencioso: un documento
    publicado y no indexado sigue siendo **citable por identidad** —si disparó, la
    pierna de autorización lo cita igual, porque esa pierna no consulta el
    índice— e **invisible por similitud**. Nada falla; simplemente el
    descubrimiento no puede alcanzarlo.
    """
    indexadas = (
        select(distinct(PolicyChunk.policy_id))
        .where(PolicyChunk.index_version == index_version)
        .scalar_subquery()
    )

    faltantes = await session.scalars(
        select(distinct(FraudPolicy.policy_id))
        .where(FraudPolicy.policy_id.notin_(indexadas))
        .order_by(FraudPolicy.policy_id)
    )

    return tuple(faltantes.all())
