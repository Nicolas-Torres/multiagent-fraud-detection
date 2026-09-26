"""Techo de uso de la demo pública (ADR-0025).

La API no tiene autenticación: sin un techo, cualquiera puede disparar el grafo
—cada ejecución son llamadas reales a Anthropic y Gemini— tantas veces como
quiera. El conteo sale de la base, no de memoria: las dos nubes comparten la
misma base y el mismo saldo del proveedor, así que el techo tiene que ser uno
solo para las dos, y sobrevivir a un reinicio del proceso.

Sólo en producción, como el caché de `/ready`: local y tests no cuentan nada.

Es un techo **blando**: dos requests simultáneos pueden pasarlo por uno o dos.
Alcanza para acotar el gasto, que es lo que protege.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from multiagent_fraud_detection.config.settings import settings

HORA = timedelta(hours=1)
DIA = timedelta(days=1)


@dataclass(frozen=True)
class Techo:
    por_hora: int
    por_dia: int | None
    que: str


EJECUCIONES = Techo(por_hora=40, por_dia=200, que="ejecuciones")
RESOLUCIONES = Techo(por_hora=20, por_dia=None, que="resoluciones")


async def exceso(
    session: AsyncSession, columna: InstrumentedAttribute, techo: Techo
) -> str | None:
    """El mensaje del techo superado, o `None` si todavía hay margen.

    Una sola consulta cuenta las dos ventanas: la de la hora filtra dentro de
    la del día.
    """
    if settings.environment != "production":
        return None

    ventana = DIA if techo.por_dia is not None else HORA
    en_la_hora, en_el_dia = (
        await session.execute(
            select(
                func.count().filter(columna >= func.now() - HORA),
                func.count(),
            ).where(columna >= func.now() - ventana)
        )
    ).one()

    if en_la_hora >= techo.por_hora:
        return (
            f"La demo alcanzó su límite de {techo.por_hora} {techo.que} por hora. "
            "Probá de nuevo más tarde."
        )
    if techo.por_dia is not None and en_el_dia >= techo.por_dia:
        return (
            f"La demo alcanzó su límite de {techo.por_dia} {techo.que} por día. "
            "Probá de nuevo mañana."
        )
    return None
