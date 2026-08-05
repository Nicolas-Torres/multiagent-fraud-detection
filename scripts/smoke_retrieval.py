"""Verifica el invariante de generación de ADR-0012 §6, sin llamar al proveedor.

    uv run python scripts/smoke_retrieval.py

Requiere haber corrido `index_policies.py` y `index_policies.py --fake`, para
que en la tabla convivan dos generaciones. Con una sola, las comprobaciones 2 y 3
no prueban nada y el script lo dice.

## Cómo se prueba sin red

La query no se embebe: se **toma prestado** el vector de un chunk ya indexado.

## Qué NO sirve para probar el filtro

Comparar conjuntos de `chunk_id` entre generaciones. Una fila se identifica por
`(index_version, chunk_id)`, y el `chunk_id` es **idéntico** entre generaciones
por diseño —es lo que hace que una cita de enero siga resolviendo contra el
índice de marzo—. Dos búsquedas correctas sobre generaciones distintas devuelven
exactamente los mismos `chunk_id`, así que esa comparación no distingue el caso
bueno del malo en ninguna dirección.

## Qué sí

**Por conteo.** Con `limit` mayor que la tabla entera, una búsqueda que filtra
devuelve las filas de *su* generación; una que no filtra las devuelve todas. El
número es prueba estructural directa del `WHERE`.

**Por distancia.** El vector real de FP-03 contra la generación `fake` no puede
dar ~0: los vectores falsos son hashes sin relación con el texto. Si el filtro se
cayera, el top-1 sería el FP-03 real a distancia 0 sin importar qué generación se
pidió.
"""

import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from multiagent_fraud_detection.db.models import PolicyChunk
from multiagent_fraud_detection.db.repositories.policy_chunks import (
    search_similar,
    unindexed_policies,
)
from multiagent_fraud_detection.db.session import engine
from multiagent_fraud_detection.retrieval.embeddings import (
    FAKE_INDEX_VERSION,
    INDEX_VERSION,
)

Session = async_sessionmaker(engine, expire_on_commit=False)

SONDA = "FP-03"

# Mayor que la tabla entera: si el filtro faltara, la búsqueda traería las filas
# de todas las generaciones y el conteo lo delataría.
LIMITE_AMPLIO = 500


async def filas_en(session, index_version: str) -> int:
    return await session.scalar(
        select(func.count())
        .select_from(PolicyChunk)
        .where(PolicyChunk.index_version == index_version)
    ) or 0


async def vector_de(session, index_version: str, policy_id: str) -> list[float] | None:
    fila = await session.scalar(
        select(PolicyChunk.embedding)
        .where(PolicyChunk.index_version == index_version)
        .where(PolicyChunk.policy_id == policy_id)
        .limit(1)
    )
    return list(fila) if fila is not None else None


async def correr() -> int:
    problemas: list[str] = []

    async with Session() as session:
        generaciones = sorted(
            (await session.scalars(select(PolicyChunk.index_version).distinct())).all()
        )
        total_tabla = await session.scalar(select(func.count()).select_from(PolicyChunk))
        print(f"generaciones en la tabla: {generaciones}")
        print(f"filas totales: {total_tabla}")

        hay_dos = len(generaciones) > 1
        if not hay_dos:
            print(
                "  aviso: hay una sola generación, así que las comprobaciones 2 y 3\n"
                "  no pueden fallar aunque el filtro no existiera.\n"
                "  Corré `index_policies.py --fake` para tener dos."
            )

        sonda = await vector_de(session, INDEX_VERSION, SONDA)
        if sonda is None:
            print(f"FALLA: no hay chunk de {SONDA} en {INDEX_VERSION}")
            return 1

        # --- 1. el vector guardado es el que se cree ------------------------
        resultados = await search_similar(session, sonda, limit=3)
        print(f"\n1. buscando con el vector de {SONDA} en {INDEX_VERSION}:")
        for r in resultados:
            print(f"   {r.policy_id:7s} {r.distance:.6f}  {r.content[:56]}")

        if not resultados or resultados[0].policy_id != SONDA:
            problemas.append(
                f"el más cercano al vector de {SONDA} debería ser {SONDA}, y fue "
                f"{resultados[0].policy_id if resultados else 'nada'}"
            )
        elif resultados[0].distance > 1e-6:
            problemas.append(
                f"la distancia de {SONDA} a sí mismo es {resultados[0].distance}, "
                f"no ~0: el vector no es el que se guardó"
            )

        # --- 2. el filtro, por conteo -------------------------------------- #
        print("\n2. alcance de una búsqueda amplia, por generación:")
        for gen in generaciones:
            esperadas = await filas_en(session, gen)
            traidas = len(
                await search_similar(
                    session, sonda, limit=LIMITE_AMPLIO, index_version=gen
                )
            )
            print(f"   {gen:34s} {traidas:3d} traídas / {esperadas:3d} en la generación")

            if traidas != esperadas:
                problemas.append(
                    f"{gen}: la búsqueda trajo {traidas} filas y la generación "
                    f"tiene {esperadas} (la tabla entera tiene {total_tabla}). "
                    f"El `WHERE index_version` no está acotando."
                )

        # --- 3. el filtro, por distancia ----------------------------------- #
        if hay_dos and FAKE_INDEX_VERSION in generaciones:
            en_falsa = await search_similar(
                session, sonda, limit=1, index_version=FAKE_INDEX_VERSION
            )
            d = en_falsa[0].distance if en_falsa else None
            print(
                f"\n3. el vector real de {SONDA} contra {FAKE_INDEX_VERSION}: "
                f"distancia mínima {d:.6f}" if d is not None else
                f"\n3. sin resultados en {FAKE_INDEX_VERSION}"
            )

            if d is not None and d < 1e-6:
                problemas.append(
                    f"buscar en {FAKE_INDEX_VERSION} con un vector real dio "
                    f"distancia {d}: la consulta está alcanzando filas de "
                    f"{INDEX_VERSION}"
                )

        # --- la tercera métrica del entregable 6 --------------------------- #
        pendientes = await unindexed_policies(session)
        print(f"\nchunks pendientes de indexar: {len(pendientes)} {list(pendientes)}")

    await engine.dispose()

    if problemas:
        print(f"\nFALLA: {len(problemas)} problemas")
        for p in problemas:
            print(f"  - {p}")
        return 1

    print("\nOK")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(correr()))
