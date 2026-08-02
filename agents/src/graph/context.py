"""Dependencias de runtime del grafo.

No es estado: no muta entre nodos, no se checkpointea y puede contener objetos
no serializables. Es lo que el grafo necesita del mundo exterior.

Se inyecta al invocar:

    await graph.ainvoke(entrada, context=GraphContext(session_factory=...))

El nodo persistidor no puede usar la sesion del request: ese ya devolvio 202 y
el grafo corre en segundo plano. Necesita su propia sesion y su propio commit.
"""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@dataclass
class GraphContext:
    session_factory: async_sessionmaker[AsyncSession]
