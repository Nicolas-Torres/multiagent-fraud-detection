from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict

from src.enums import CaseStatus, DecisionType
from src.schemas.customer_behavior import CustomerBehaviorRead
from src.schemas.decision import DecisionRead
from src.schemas.human_resolution import HumanResolutionRead
from src.schemas.transaction import TransactionRead
from src.schemas.types import Confidence, Money

if TYPE_CHECKING:
    from src.db.models.case import Case


class CaseCreated(BaseModel):
    """Respuesta del POST /cases (202 nuevo / 200 reintento idempotente)."""

    model_config = ConfigDict(from_attributes=True)

    case_id: UUID
    status: CaseStatus
    created_at: AwareDatetime


class CaseDetail(BaseModel):
    """Respuesta del GET /cases/{case_id}."""

    model_config = ConfigDict(from_attributes=True)

    case_id: UUID
    status: CaseStatus
    transaction: TransactionRead
    customer: CustomerBehaviorRead | None
    decision: DecisionRead | None
    human_resolution: HumanResolutionRead | None
    created_at: AwareDatetime
    updated_at: AwareDatetime


class CaseSummary(BaseModel):
    """Proyección plana para la cola HITL (GET /cases)."""

    case_id: UUID
    status: CaseStatus
    decision: DecisionType | None
    confidence: Confidence | None
    amount: Money
    customer_id: str
    created_at: AwareDatetime

    @classmethod
    def from_case(cls, case: "Case") -> "CaseSummary":
        return cls(
            case_id=case.case_id,
            status=case.status,
            decision=case.decision.decision if case.decision else None,
            confidence=case.decision.confidence if case.decision else None,
            amount=case.transaction.amount,
            customer_id=case.transaction.customer_id,
            created_at=case.created_at,
        )
