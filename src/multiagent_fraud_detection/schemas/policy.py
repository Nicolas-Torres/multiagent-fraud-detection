from pydantic import BaseModel, ConfigDict

from multiagent_fraud_detection.domain.catalog import PolicyState
from multiagent_fraud_detection.enums import DecisionType


class PolicyRead(BaseModel):
    """Respuesta de `GET /api/v1/policies` (ADR-0017: sólo lectura, sobre el
    catálogo de Fase 2 — `domain.catalog.Policy`, no una tabla)."""

    model_config = ConfigDict(from_attributes=True)

    policy_id: str
    version: str
    text: str
    state: PolicyState
    action: DecisionType | None = None
    evaluable: bool
    excluded_reason: str | None = None
    bound_by: str | None = None
