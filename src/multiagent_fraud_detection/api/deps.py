"""Dependencias inyectables de FastAPI: sesión de base y el grafo compilado
con su `GraphContext`, ya armados en el `lifespan` de `api/app.py`.

Centralizarlas acá —en vez de que cada router las declare por su cuenta— es
lo que le da a `app.dependency_overrides` un punto de enganche estable: un
test sobreescribe `get_session` una sola vez y todos los routers que la usan
quedan con un doble, sin tocar Postgres.

`get_session` **envuelve** `db.session.get_async_session` en vez de
reexportarla: `dependency_overrides` engancha por identidad de función, y una
reexportación (`get_session = get_async_session`) sería el mismo objeto bajo
otro nombre, no un punto de enganche propio de esta capa.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from multiagent_fraud_detection.db.session import get_async_session
from multiagent_fraud_detection.graph.context import GraphContext


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async for session in get_async_session():
        yield session


def get_graph(request: Request) -> Any:
    return request.app.state.graph


def get_graph_context(request: Request) -> GraphContext:
    return request.app.state.graph_context
