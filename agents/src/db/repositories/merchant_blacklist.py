"""Lookup de la lista negra de comercios (insumo de FP-07).

El contrato dice que `merchant_blacklist` se cachea en memoria con invalidación
al escribir (§4). La lista es pequeña (unidades de filas), se lee en cada caso y
un índice no aportaría: se carga completa una vez y se refresca al escribir.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import MerchantBlacklist

# Cache en memoria del conjunto de comercios activos. Invalidación: al escribir,
# el llamador borra esta variable global. Es un cache de un proceso; con N
# réplicas cada una mantiene el suyo y el refresh lo dispara quien escribe.
_cached: frozenset[str] | None = None


def invalidate_cache() -> None:
    global _cached
    _cached = None


async def active_merchants(session: AsyncSession) -> frozenset[str]:
    """Conjunto de comercios activos de la lista negra."""
    global _cached
    if _cached is None:
        filas = await session.scalars(
            select(MerchantBlacklist.merchant_id).where(
                MerchantBlacklist.active.is_(True)
            )
        )
        _cached = frozenset(filas.all())
    return _cached
