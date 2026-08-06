from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class WebSearchAllowlistIn(BaseModel):
    """Alta de un dominio en el allowlist de búsqueda.

    No llega por HTTP —todavía—: hoy su única fuente es el script de seed.
    Existe igual que `MerchantBlacklistIn`: el dominio recibe datos canónicos
    por una frontera, sin importar quién los produzca.

    `added_at` no aparece: lo acuña el servidor.
    """

    domain: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    added_by: str = Field(min_length=1)
    active: bool = True


class WebSearchAllowlistRead(WebSearchAllowlistIn):
    model_config = ConfigDict(from_attributes=True)

    added_at: AwareDatetime
