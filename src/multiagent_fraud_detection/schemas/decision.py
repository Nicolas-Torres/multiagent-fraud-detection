from pydantic import AwareDatetime, BaseModel, Field, HttpUrl


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
