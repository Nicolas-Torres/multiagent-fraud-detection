from pydantic import AwareDatetime, BaseModel, Field, HttpUrl, ConfigDict

from multiagent_fraud_detection.enums import DecisionType, Severity
from multiagent_fraud_detection.schemas.types import Confidence

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
    confidence: Confidence
    signals: list[SignalRead]
    citations_internal: list[InternalCitation]
    citations_external: list[ExternalCitation]
    debate: DebateSummary
    agent_route: list[str]
    explanation_customer: str
    explanation_audit: str
    decided_at: AwareDatetime
