"""Dependencias de runtime del grafo.

No es estado: no muta entre nodos, no se checkpointea y puede contener objetos
no serializables. Es lo que el grafo necesita del mundo exterior.

Se inyecta al invocar:

    await graph.ainvoke(entrada, context=GraphContext(session_factory=...))

El nodo persistidor no puede usar la sesion del request: ese ya devolvio 202 y
el grafo corre en segundo plano. Necesita su propia sesion y su propio commit.

D10: los agentes con LLM reciben el cliente por `context_schema`, no por el
estado. MLflow NO entra aca (D9): el tracking vive en el harness.
"""

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# Tipo ancho a proposito: el cliente concreto depende del proveedor (D10) y no
# deberia filtrarse al resto del grafo.
LlmProvider = Any
EmbeddingsClient = Any


@dataclass
class GraphContext:
    session_factory: async_sessionmaker[AsyncSession]
    llm: LlmProvider | None = None
    embeddings: EmbeddingsClient | None = None
    llm_provider: str = "anthropic"
    threat_intel_offline: bool = False
    extra: dict[str, Any] = field(default_factory=dict)
