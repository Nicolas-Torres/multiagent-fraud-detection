from datetime import datetime

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class WebSearchAllowlistIn(BaseModel):
    """Alta de un dominio en la lista permitida de búsqueda web.

    Dato de gobernanza (contrato §4): no llega por HTTP todavía; hoy su única
    fuente es el script de seed. `added_at` lo acuña el servidor, igual que en
    `MerchantBlacklistIn`.
    """

    domain: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    added_by: str = Field(min_length=1)
    active: bool = True


class WebSearchAllowlistRead(WebSearchAllowlistIn):
    model_config = ConfigDict(from_attributes=True)

    added_at: AwareDatetime
