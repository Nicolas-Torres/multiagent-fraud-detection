from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from multiagent_fraud_detection.enums import Channel
from multiagent_fraud_detection.schemas.types import CountryCode, CurrencyCode, Money


class TransactionIn(BaseModel):
    """Entrada canónica de una transacción a evaluar."""

    transaction_id: str = Field(min_length=1)
    customer_id: str = Field(min_length=1)
    amount: Money

    # Extraído a `types.py` al aparecer el segundo consumidor
    # (`CustomerBehaviorIn`). No es solo reuso: el sistema **compara** las dos
    # monedas —la de la transacción es la de la cuenta—, así que tienen que ser
    # el mismo tipo o la divergencia aparece en tiempo de ejecución.
    currency: CurrencyCode

    country: CountryCode
    channel: Channel
    device_id: str = Field(min_length=1)
    timestamp: AwareDatetime
    merchant_id: str = Field(min_length=1)


class TransactionRead(TransactionIn):
    model_config = ConfigDict(from_attributes=True)
