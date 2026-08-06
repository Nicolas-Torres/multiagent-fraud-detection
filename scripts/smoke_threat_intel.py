"""Verifica el snapshot congelado de ADR-0014, contra Postgres real.

    uv run python scripts/smoke_threat_intel.py

Dos invariantes, cada uno con su propia guarda.

## 1. El fetch es idempotente

`ON CONFLICT` sobre `uq_threat_indicators_observation` tiene que actualizar,
no duplicar. Se corre `fetch_threat_intel.py --fake` **dos veces**, como
proceso aparte —igual que lo correría alguien desde la terminal, y no una
llamada a su función interna— y se compara el conteo de filas bajo
`FAKE_SNAPSHOT_VERSION`.

## 2. `active_indicators` no mezcla generaciones

Mismo invariante que ADR-0012 §6 verifica para el índice de políticas
(`smoke_retrieval.py`), y misma trampa si se prueba mal: comparar contenido no
alcanza, porque dos generaciones pueden traer datos parecidos y aun así
filtrar mal. Se prueba por **conteo** — se siembra un indicador sintético bajo
la generación real, junto a las filas `--fake` que ya conviven en la tabla
después del paso 1, y se confirma que el lookup sólo ve la suya.
"""

import asyncio
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from multiagent_fraud_detection.db.models import ThreatIndicator
from multiagent_fraud_detection.db.repositories.threat_indicator import (
    active_indicators,
)
from multiagent_fraud_detection.db.session import engine
from multiagent_fraud_detection.enums import IndicatorType
from multiagent_fraud_detection.intel.snapshot import (
    FAKE_SNAPSHOT_VERSION,
    SNAPSHOT_VERSION,
)

Session = async_sessionmaker(engine, expire_on_commit=False)

FETCH_SCRIPT = Path(__file__).with_name("fetch_threat_intel.py")

# Sintético, y con un prefijo que no coincide con ningún código de emisor real
# del dataset: si apareciera en un lookup de verdad, se nota.
EMISOR_SONDA = "SMOKE-ISSUER"


def correr_fetch_fake() -> None:
    subprocess.run(
        [sys.executable, str(FETCH_SCRIPT), "--fake"],
        check=True,
    )


async def _filas_bajo(session, snapshot_version: str) -> int:
    return await session.scalar(
        select(func.count())
        .select_from(ThreatIndicator)
        .where(ThreatIndicator.snapshot_version == snapshot_version)
    ) or 0


async def _limpiar_sonda(session) -> None:
    await session.execute(
        delete(ThreatIndicator).where(ThreatIndicator.value == EMISOR_SONDA)
    )


async def correr() -> int:
    problemas: list[str] = []

    # --- 1. idempotencia del fetch --------------------------------------- #
    print("1. fetch_threat_intel.py --fake, dos corridas")
    correr_fetch_fake()
    async with Session() as session:
        primera = await _filas_bajo(session, FAKE_SNAPSHOT_VERSION)

    correr_fetch_fake()
    async with Session() as session:
        segunda = await _filas_bajo(session, FAKE_SNAPSHOT_VERSION)

    print(f"   {primera} filas -> {segunda} filas bajo {FAKE_SNAPSHOT_VERSION}")
    if primera == 0:
        problemas.append(
            "la primera corrida no dejó filas: revisá que el allowlist esté "
            "sembrado (`uv run python scripts/seed.py`)"
        )
    elif primera != segunda:
        problemas.append(
            f"el conteo cambió entre corridas ({primera} -> {segunda}): el "
            f"ON CONFLICT está duplicando en vez de actualizar"
        )

    # --- 2. active_indicators no mezcla generaciones --------------------- #
    print(f"\n2. una fila sintética bajo la generación real, junto a las --fake")
    ahora = datetime.now(timezone.utc)
    async with Session() as session:
        async with session.begin():
            await _limpiar_sonda(session)
            session.add(
                ThreatIndicator(
                    indicator_type=IndicatorType.ISSUER,
                    value=EMISOR_SONDA,
                    observed_at=ahora - timedelta(hours=1),
                    retrieved_at=ahora,
                    source_url="https://sbs.gob.pe/alertas/smoke",
                    summary="Fila sintética del smoke (no es una alerta real)",
                    snapshot_version=SNAPSHOT_VERSION,
                    added_by="smoke",
                )
            )

    try:
        async with Session() as session:
            indice = await active_indicators(session)
            total_real = await _filas_bajo(session, SNAPSHOT_VERSION)
            total_fake = await _filas_bajo(session, FAKE_SNAPSHOT_VERSION)

        print(
            f"   {total_real} filas en {SNAPSHOT_VERSION} · "
            f"{total_fake} en {FAKE_SNAPSHOT_VERSION}"
        )
        print(f"   active_indicators() devolvió {len(indice)} claves (tipo, valor)")

        if (IndicatorType.ISSUER, EMISOR_SONDA) not in indice:
            problemas.append(
                f"la fila sintética bajo {SNAPSHOT_VERSION} no apareció en el "
                f"lookup: el filtro está descartando su propia generación"
            )

        # Si el WHERE dejara de acotar por generación, el lookup traería
        # también los emisores de las filas `--fake`, no sólo la sonda.
        async with Session() as session:
            valores_fake = set(
                (
                    await session.scalars(
                        select(ThreatIndicator.value).where(
                            ThreatIndicator.snapshot_version == FAKE_SNAPSHOT_VERSION
                        )
                    )
                ).all()
            )

        colados = {v for (_, v) in indice} & valores_fake
        if colados:
            problemas.append(
                f"active_indicators() trajo {len(colados)} emisores de "
                f"{FAKE_SNAPSHOT_VERSION}: el filtro por generación no está "
                f"acotando"
            )
    finally:
        # La sonda no debe sobrevivir entre corridas del smoke.
        async with Session() as session:
            async with session.begin():
                await _limpiar_sonda(session)

    await engine.dispose()

    if problemas:
        print(f"\nFALLA: {len(problemas)} problemas")
        for p in problemas:
            print(f"  - {p}")
        return 1

    print("\nOK")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(correr()))
