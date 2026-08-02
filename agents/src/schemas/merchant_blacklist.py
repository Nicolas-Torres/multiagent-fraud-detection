from datetime import datetime

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class MerchantBlacklistIn(BaseModel):
    """Alta de un comercio en la lista negra.

    No llega por HTTP —todavía—: hoy su única fuente es el script de seed. Existe
    igual porque el dominio recibe datos canónicos por una frontera, sin importar
    quién los produzca. El día que haya un endpoint de administración, este es su
    body.

    `added_at` no aparece: lo acuña el servidor. Es la misma razón por la que
    `HumanResolutionIn` no lleva `resolved_at` —si viniera en el request, alguien
    podría antedatar su propia decisión en una cola de auditoría—.
    """

    merchant_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    added_by: str = Field(min_length=1)
    active: bool = True


class MerchantBlacklistRead(MerchantBlacklistIn):
    model_config = ConfigDict(from_attributes=True)

    added_at: AwareDatetime
