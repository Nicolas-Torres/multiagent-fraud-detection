from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from multiagent_fraud_detection.db.base import Base


class WebSearchAllowlist(Base):
    """Fuentes autorizadas para la búsqueda web gobernada. Insumo de `fetch_threat_intel.py` (ADR-0014).

    Tercera tabla de gobernanza, hermana de `merchant_blacklist`. **El allowlist
    gobierna el camino de escritura, no el de lectura**: `fetch_threat_intel.py`
    la lee para decidir qué fuentes puede consultar; el grafo en runtime nunca
    la toca —lo que ya pasó el filtro y quedó en `threat_indicators` es lo único
    que el nodo `external_threat_intel` ve—.

    **Nombre en singular**, igual que `merchant_blacklist`: describe la lista,
    no sus filas.

    **Sin columna de umbral ni de severidad**: una fuente está o no está
    autorizada. Lo que decide la política es la evidencia que trae, no la
    fuente que la trajo.
    """

    __tablename__ = "web_search_allowlist"

    # PK natural con bandera `active`, mismo criterio que `merchant_blacklist`:
    # el lookup real es "¿este dominio está autorizado?", y retirar una fuente
    # es una decisión de gobernanza que hay que poder auditar, no un borrado.
    domain: Mapped[str] = mapped_column(String, primary_key=True)

    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))

    #: Quién autorizó la fuente y por qué. No es metadata: es el registro de
    #: gobernanza que hace auditable la decisión de confiar en este dominio.
    reason: Mapped[str] = mapped_column(Text)

    added_by: Mapped[str] = mapped_column(String)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Sin índice en `active`: la lee un script de build una vez por corrida, no
    # el grafo. Mismo criterio que `merchant_blacklist`.
