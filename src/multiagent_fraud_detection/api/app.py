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
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from multiagent_fraud_detection.api.deps import get_session
from multiagent_fraud_detection.db.session import AsyncSessionLocal
from multiagent_fraud_detection.graph.builder import build_graph
from multiagent_fraud_detection.graph.context import GraphContext

# Hermano de raíz (§0/§4.1 del briefing), no dentro de `src/`. `dist/` es
# artefacto de build de `dashboard/` —gitignored—, así que no existe hasta
# que alguien corre `npm run build` o el Dockerfile multi-etapa lo genera.
DASHBOARD_DIST = Path(__file__).resolve().parents[3] / "dashboard" / "dist"


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

    from multiagent_fraud_detection.api.routers import cases, metrics, policies, predicates

    app.include_router(cases.router, prefix="/api/v1")
    app.include_router(metrics.router, prefix="/api/v1")
    app.include_router(policies.router, prefix="/api/v1")
    app.include_router(predicates.router, prefix="/api/v1")

    # El dashboard, si está compilado. Va al final a propósito: un
    # catch-all registrado antes le robaría el matching a `/api/v1/*`. Sin
    # `dist/` (backend puro, tests, CI) no se registra nada de esto — el
    # árbol Python no depende de que el frontend se haya compilado.
    if DASHBOARD_DIST.is_dir():
        app.mount(
            "/assets",
            StaticFiles(directory=DASHBOARD_DIST / "assets"),
            name="dashboard-assets",
        )

        @app.get("/{full_path:path}")
        async def dashboard_spa(full_path: str) -> FileResponse:
            """Sirve el SPA. Un archivo real del root de `dist/` (p.ej.
            `favicon.svg`) se sirve por su nombre exacto; cualquier otra ruta
            es del router del lado del cliente (React Router) y cae a
            `index.html` — `StaticFiles(html=True)` sólo resuelve URLs de
            directorio, no rutas profundas como `/cases/{id}`."""
            candidato = DASHBOARD_DIST / full_path
            if full_path and candidato.is_file():
                return FileResponse(candidato)
            return FileResponse(DASHBOARD_DIST / "index.html")

    return app


app = create_app()
