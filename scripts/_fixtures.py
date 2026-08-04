"""Siembra compartida por los smoke tests que corren el grafo.

Desde que `persist_decision` escribe de verdad, correr el grafo exige una
transaccion y un caso en la base: las FK de `cases` y `decisions` no se
satisfacen solas.

Cuando llegue pytest (entregable 5) esto se vuelve una fixture. El trabajo no
se tira: se reordena.
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import delete

from multiagent_fraud_detection.db.models import Case, MerchantBlacklist, Transaction
from multiagent_fraud_detection.db.session import AsyncSessionLocal
from multiagent_fraud_detection.enums import CaseStatus, Channel
from multiagent_fraud_detection.graph.context import GraphContext
from multiagent_fraud_detection.schemas.transaction import TransactionIn

# El contexto de runtime que el grafo necesita para persistir.
CONTEXTO = GraphContext(session_factory=AsyncSessionLocal)

# Comercio propio del smoke, no `M-999` del dataset: asi el script no depende de
# que alguien haya corrido `seed.py`, y su limpieza no puede borrar datos
# sembrados. Un fixture que ensucia el dataset deja de ser un fixture.
MERCHANT_SMOKE = "M-SMOKE"


def transaccion(tx_id: str) -> TransactionIn:
    """La T-1002 del reto: monto y horario fuera de lo habitual."""
    return TransactionIn(
        transaction_id=tx_id,
        customer_id="CU-002",
        amount=Decimal("9500.00"),
        currency="PEN",
        country="PE",
        channel=Channel.MOBILE,
        device_id="D-02",
        timestamp=datetime(2025, 12, 17, 23, 45, tzinfo=UTC),
        # En lista negra a proposito: con un comercio limpio, Transaction Context
        # no produce ninguna senal y el smoke no podria comprobar que el reducer
        # acumula entre dos ramas paralelas —que es lo que vino a probar—.
        merchant_id=MERCHANT_SMOKE,
    )


async def limpiar(case_id: UUID, tx_id: str) -> None:
    """El ON DELETE CASCADE arrastra decisions, signals y agent_errors."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await session.execute(delete(Case).where(Case.case_id == case_id))
            await session.execute(
                delete(Transaction).where(Transaction.transaction_id == tx_id)
            )
            await session.execute(
                delete(MerchantBlacklist).where(
                    MerchantBlacklist.merchant_id == MERCHANT_SMOKE
                )
            )


async def sembrar(case_id: UUID, tx_id: str) -> None:
    """Deja el caso en ANALYZING, que es el estado desde el que corre el grafo."""
    await limpiar(case_id, tx_id)
    tx = transaccion(tx_id)
    async with AsyncSessionLocal() as session:
        async with session.begin():
            session.add(
                Transaction(**tx.model_dump())
            )
            session.add(
                Case(
                    case_id=case_id,
                    transaction_id=tx_id,
                    status=CaseStatus.ANALYZING,
                )
            )
            session.add(
                MerchantBlacklist(
                    merchant_id=MERCHANT_SMOKE,
                    reason="Comercio de prueba del smoke test",
                    added_by="smoke",
                )
            )
