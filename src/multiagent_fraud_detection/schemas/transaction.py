from decimal import Decimal
from pydantic import AwareDatetime, BaseModel, Field
from multiagent_fraud_detection.enums import Channel

class TransactionIn(BaseModel):
    transaction_id: str
    customer_id: str
    amount: Decimal = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)
    country: str = Field(min_length=2, max_length=2)
    channel: Channel
    device_id: str
    timestamp: AwareDatetime
    merchant_id: str
