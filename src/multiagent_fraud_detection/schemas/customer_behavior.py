from pydantic import BaseModel, Field

from multiagent_fraud_detection.schemas.types import CountryCode, Money

class CustomerBehaviorIn(BaseModel):
    """Perfil de comportamiento habitual del cliente."""
    customer_id: str = Field(min_length=1)
    usual_amount_avg: Money
    usual_hour_start: int = Field(ge=0, le=23)
    usual_hour_end: int = Field(ge=0, le=23)
    usual_countries: list[CountryCode]
    usual_devices: list[str]
