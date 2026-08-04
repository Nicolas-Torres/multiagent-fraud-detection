from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from src.enums import HumanAction


class HumanResolutionIn(BaseModel):
    """Body del POST /cases/{case_id}/resolution."""

    action: HumanAction
    analyst_id: str = Field(min_length=1)
    notes: str | None = None


class HumanResolutionRead(HumanResolutionIn):
    model_config = ConfigDict(from_attributes=True)

    resolved_at: AwareDatetime
