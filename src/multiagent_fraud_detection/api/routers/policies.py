"""`GET /api/v1/policies`: de solo lectura sobre el catálogo de Fase 2
(ADR-0017). Sin `POST` acá: dar de alta una política necesita un destino
seguro para escrituras concurrentes que un archivo no da — la Fase 3
(tablas) es una etapa aparte, no ésta.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from multiagent_fraud_detection.api.deps import get_graph_context
from multiagent_fraud_detection.graph.context import GraphContext
from multiagent_fraud_detection.schemas.policy import PolicyRead

router = APIRouter(tags=["policies"])


@router.get("/policies", response_model=list[PolicyRead])
async def listar_politicas(
    contexto: GraphContext = Depends(get_graph_context),
) -> list[PolicyRead]:
    """El catálogo ya vive en `app.state` —lo arma el `lifespan`, no este
    endpoint—: releerlo por request revalidaría dos archivos por nada."""
    return [PolicyRead.model_validate(p) for p in contexto.catalog.policies]
