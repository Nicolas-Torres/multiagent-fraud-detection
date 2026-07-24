from typing import Annotated

from pydantic import AwareDatetime, BaseModel, Field, StringConstraints, ConfigDict

from multiagent_fraud_detection.enums import Channel
from multiagent_fraud_detection.schemas.types import CountryCode, Money

class TransactionIn(BaseModel):
    """Entrada canónica de una transacción a evaluar."""
    transaction_id: str = Field(min_length=1)
    customer_id: str = Field(min_length=1)
    amount: Money
    currency: Annotated[
        str, StringConstraints(min_length=3, max_length=3, to_upper=True)
    ]
    country: CountryCode
    channel: Channel
    device_id: str = Field(min_length=1)
    timestamp: AwareDatetime
    merchant_id: str = Field(min_length=1)

class TransactionRead(TransactionIn):
    model_config = ConfigDict(from_attributes=True)
