"""El proceso real: la app FastAPI, con un `GraphContext` por proceso.

## Un solo `GraphContext`, armado una vez

`graph/context.py` ya lo documenta para el catálogo: cargarlo por request
relee y revalida dos archivos. El `lifespan` arma el grafo compilado y el
`GraphContext` al arrancar el proceso y los deja en `app.state`; los routers
los leen de ahí, nunca los reconstruyen.

## El entry point real, no un script suelto

`WindowsSelectorEventLoopPolicy` se fija acá y sólo acá: es el único punto de
entrada del proceso servido. Los scripts sueltos (`smoke_decision.py`, etc.)
la fijan cada uno porque cada uno *es* un proceso; un router de esta app no
tiene que volver a hacerlo.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from multiagent_fraud_detection.api.deps import get_session
from multiagent_fraud_detection.db.session import AsyncSessionLocal
from multiagent_fraud_detection.graph.builder import build_graph
from multiagent_fraud_detection.graph.context import GraphContext


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    app.state.graph = build_graph()
    app.state.graph_context = GraphContext(session_factory=AsyncSessionLocal)
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Sistema Multi-Agente de Detección de Fraude",
        lifespan=lifespan,
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        """Liveness: el proceso responde. No toca la base."""
        return {"status": "ok"}

    @app.get("/ready")
    async def ready(session: AsyncSession = Depends(get_session)) -> dict[str, str]:
        """Readiness: Postgres responde. Un `SELECT 1` sin éxito propaga la
        excepción a un `500` — la señal correcta para un probe, no un caso a
        degradar.

        La sesión llega por `Depends`, no por `AsyncSessionLocal` directo:
        es lo que le permite a un test sobreescribirla con un doble sin
        tocar Postgres — ver `tests/test_api_health.py`."""
        await session.execute(text("SELECT 1"))
        return {"status": "ok"}

    from multiagent_fraud_detection.api.routers import cases, policies

    app.include_router(cases.router, prefix="/api/v1")
    app.include_router(policies.router, prefix="/api/v1")

    # El router que falta se agrega en el paso siguiente del plan de la
    # etapa (`docs/plan_api_hitl.md`): predicates.

    return app


app = create_app()
