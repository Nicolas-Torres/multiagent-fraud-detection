"""Acceso a la lista permitida de dominios para la búsqueda web gobernada.

Dato de gobernanza (contrato §4): mutable, con audit trail, vive en una tabla.
La consulta real es un lookup puntual por dominio, por eso se modela como tabla
y no como env var. Se cachea en memoria con invalidación al escribir (D6),
igual que `merchant_blacklist`.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import WebSearchAllowlist

# Cache en memoria del conjunto de dominios activos. Invalidación: al escribir,
# el llamador borra la variable global. Cache de un proceso; con N réplicas cada
# una mantiene el suyo y el refresh lo dispara quien escribe.
_cached: frozenset[str] | None = None


def invalidate_cache() -> None:
    global _cached
    _cached = None


async def list_allowed(session: AsyncSession) -> frozenset[str]:
    """Conjunto de dominios activos (para el nodo Threat Intel)."""
    global _cached
    if _cached is None:
        filas = await session.scalars(
            select(WebSearchAllowlist.domain).where(
                WebSearchAllowlist.active.is_(True)
            )
        )
        _cached = frozenset(filas.all())
    return _cached


async def is_allowed(session: AsyncSession, domain: str) -> bool:
    """¿El dominio está en la lista permitida y activo?"""
    return domain in await list_allowed(session)
