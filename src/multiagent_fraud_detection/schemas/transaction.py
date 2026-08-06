from typing import Annotated

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints

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

    # Insumo de FP-10 (ADR-0015). `to_upper` es transformación sin pérdida
    # —la excepción que documenta `CLAUDE.md`—: el predicado compara por
    # igualdad exacta contra `threat_indicators.value`, y una diferencia de
    # mayúsculas ahí sería un falso negativo silencioso, no un error visible.
    # Nullable porque no todo emisor del dataset está en el corpus de amenazas.
    issuer_bank: Annotated[
        str, StringConstraints(min_length=1, max_length=16, to_upper=True)
    ] | None = None


class TransactionRead(TransactionIn):
    model_config = ConfigDict(from_attributes=True)
