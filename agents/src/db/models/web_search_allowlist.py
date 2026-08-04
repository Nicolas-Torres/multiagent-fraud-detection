from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base


class WebSearchAllowlist(Base):
    """Dominios permitidos para la búsqueda web gobernada del Threat Intel Agent.

    **Dato de gobernanza**, no config de infraestructura (contrato §4): mutable,
    administrado por un humano, con audit trail. Comparte la forma de
    `merchant_blacklist` —PK natural con baja lógica `active`— por la misma
    razón: la consulta real es un lookup puntual y el historial no se pierde
    porque el caso congela su evidencia en `citations_external`.

    Sin embargo, **no** se cachea en memoria como `merchant_blacklist`: el
    allowlist se consulta en cada corrida del Threat Intel Agent y se mantiene
    pequeño; el cache con invalidación queda como mejora si crece.
    """

    __tablename__ = "web_search_allowlist"

    domain: Mapped[str] = mapped_column(String, primary_key=True)

    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))

    reason: Mapped[str] = mapped_column(Text)

    added_by: Mapped[str] = mapped_column(String)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
