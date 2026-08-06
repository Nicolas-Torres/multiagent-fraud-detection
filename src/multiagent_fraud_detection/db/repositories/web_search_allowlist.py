"""El allowlist de búsqueda web: lectura para el fetch.

Sin caché de proceso, a diferencia de `merchant_blacklist` y de
`ThreatIndicator`. Las dos cachean porque el grafo las lee una vez por
transacción; ésta la lee `fetch_threat_intel.py`, una vez por corrida de build
(ADR-0014). No hay lectura repetida en runtime que justifique el TTL ni la
invalidación.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from multiagent_fraud_detection.db.models import WebSearchAllowlist


async def active_domains(session: AsyncSession) -> frozenset[str]:
    """Los dominios vigentes. `active=False` es baja lógica: no cuenta."""
    stmt = select(WebSearchAllowlist.domain).where(WebSearchAllowlist.active)
    return frozenset((await session.scalars(stmt)).all())
