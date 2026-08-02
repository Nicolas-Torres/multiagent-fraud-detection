from datetime import date

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from agents.src.enums import Channel, Segment
from agents.src.schemas.types import CountryCode, CurrencyCode, Money, TimeZone


class CustomerBehaviorIn(BaseModel):
    """Perfil de comportamiento habitual del cliente.

    No llega por HTTP: su frontera es el dataset, no el API. La normalización de
    formato (`"08-20"` → `(8, 20)`, `"PE;ES"` → `["PE", "ES"]`) vive en el script
    de seed; acá llega el dato canónico.
    """

    customer_id: str = Field(min_length=1)
    usual_amount_avg: Money
    usual_hour_start: int = Field(ge=0, le=23)
    usual_hour_end: int = Field(ge=0, le=23)
    usual_countries: list[CountryCode]
    usual_devices: list[str]

    # --- campos de evaluación de políticas ------------------------------------
    # `usual_channel` es singular y no lista a propósito: `Channel` tiene dos
    # valores, así que una lista tendría un elemento —idéntico al singular— o los
    # dos, y entonces FP-06 ("canal nuevo con monto alto") nunca podría
    # dispararse. Se revisa el día que `Channel` crezca (ATM, POS, API).
    usual_channel: Channel

    account_creation_date: date
    last_profile_update: AwareDatetime
    daily_limit: Money

    # --- atributos de la cuenta -----------------------------------------------
    # La moneda es de la cuenta, no del país donde ocurre la compra: una tarjeta
    # liquida siempre en la moneda de su cuenta. Es lo que hace comparable
    # `usual_amount_avg` con `amount`.
    currency: CurrencyCode

    # `usual_hour_start/end` son hora **local**. Sin esta columna la ventana se
    # evaluaría en UTC y el sistema juzgaría otra franja: el dataset tiene siete
    # países, y US y MX abarcan varias zonas cada uno.
    timezone: TimeZone

    # FP-08 compara contra el promedio del **segmento**, no contra el del propio
    # cliente. Sin esta columna la política no se distingue de "5x su promedio".
    segment: Segment


class CustomerBehaviorRead(CustomerBehaviorIn):
    model_config = ConfigDict(from_attributes=True)
