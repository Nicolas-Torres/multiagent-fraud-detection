from typing import Annotated

from pydantic import AwareDatetime, BaseModel, Field, HttpUrl, ConfigDict

from src.enums import DecisionType, Severity
from src.schemas.types import Confidence

RiskScore = Annotated[float, Field(ge=0.0, le=1.0)]
ScoringVersion = Annotated[str, Field(min_length=1, max_length=16)]

class InternalCitation(BaseModel):
    policy_id: str = Field(min_length=1)
    chunk_id: str = Field(min_length=1)
    version: str = Field(min_length=1)


class ExternalCitation(BaseModel):
    url: HttpUrl
    summary: str = Field(min_length=1)
    retrieved_at: AwareDatetime


class DebateSummary(BaseModel):
    pro_fraud_argument: str = Field(min_length=1)
    pro_customer_argument: str = Field(min_length=1)


class SignalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    description: str
    severity: Severity


class DecisionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    decision: DecisionType
    risk_score: RiskScore | None = None
    confidence: Confidence
    base_confidence: Confidence | None = None
    confidence_rationale: str | None = None
    scoring_version: ScoringVersion | None = None
    signals: list[SignalRead]
    signals: list[SignalRead]
    citations_internal: list[InternalCitation]
    citations_external: list[ExternalCitation]
    debate: DebateSummary
    agent_route: list[str]
    degraded_agents: list[str]
    explanation_customer: str
    explanation_audit: str
    decided_at: AwareDatetime
