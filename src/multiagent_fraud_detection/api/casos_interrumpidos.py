"""Casos que quedaron a mitad de camino cuando el proceso se reinició.

El grafo corre como tarea en segundo plano dentro del proceso de la API
(`routers/cases._correr_grafo`). Si el proceso muere a mitad de un análisis
—un deploy que reemplaza la réplica, un `--reload` en local—, la tarea muere
con él y el caso queda en `ANALYZING` (o en `RECEIVED`, si murió antes de
empezar) para siempre: el `except` que escribe `FAILED` nunca llega a correr.

Un caso así enciende el "Analizando en vivo" del dashboard indefinidamente y
un navegador que guardó su id lo sigue consultando. Al arrancar, la API los
cierra como `FAILED`: nadie los va a terminar.

**Diez minutos** de margen: un análisis tarda entre 15 y 40 s, así que un caso
más viejo que eso no está corriendo en ninguna réplica —tampoco en la otra
nube, que comparte la base—.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import func, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql.dml import Update

from multiagent_fraud_detection.db.models import Case
from multiagent_fraud_detection.enums import CaseStatus

logger = logging.getLogger(__name__)

ANTIGUEDAD_MINIMA = timedelta(minutes=10)
EN_CURSO = (CaseStatus.RECEIVED, CaseStatus.ANALYZING)


def sentencia() -> Update:
    return (
        update(Case)
        .where(Case.status.in_(EN_CURSO))
        .where(Case.updated_at < func.now() - ANTIGUEDAD_MINIMA)
        .values(status=CaseStatus.FAILED)
    )


async def cerrar_interrumpidos(
    session_factory: async_sessionmaker[AsyncSession],
) -> int:
    """Marca `FAILED` los casos en curso sin cambios hace más de 10 minutos.

    Nunca propaga: un fallo acá no puede impedir que la API arranque.
    """
    try:
        async with session_factory() as session, session.begin():
            resultado = await session.execute(sentencia())
    except Exception:
        logger.exception("no se pudieron cerrar los casos interrumpidos")
        return 0
    if resultado.rowcount:
        logger.warning(
            "%d caso(s) interrumpido(s) por un reinicio, marcados FAILED",
            resultado.rowcount,
        )
    return resultado.rowcount


if __name__ == "__main__":
    # En local no corre al arrancar (ver `api/app.py`): se limpia a mano.
    import asyncio
    import sys

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    from multiagent_fraud_detection.db.session import AsyncSessionLocal

    cerrados = asyncio.run(cerrar_interrumpidos(AsyncSessionLocal))
    print(f"{cerrados} caso(s) interrumpido(s) marcados FAILED")
