"""Smoke test de la capa Read: escribe dos casos, los relee y los valida.

Caso A: completo (decisión + señales + resolución humana + snapshot).
Caso B: mínimo (ANALYZING, sin decisión ni snapshot) -> ejercita las ramas nulables.
"""

import asyncio
import sys
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker

from multiagent_fraud_detection.db.models import (
    Case, Decision, HumanResolution, Signal, Transaction,
)
from multiagent_fraud_detection.db.session import engine  # <- ajusta si se llama distinto
from multiagent_fraud_detection.enums import (
    CaseStatus, Channel, DecisionType, HumanAction, Severity,
)
from multiagent_fraud_detection.schemas.case import CaseDetail, CaseSummary
from multiagent_fraud_detection.schemas.customer_behavior import CustomerBehaviorIn
from multiagent_fraud_detection.schemas.decision import ExternalCitation, InternalCitation

CASE_A = UUID("00000000-0000-0000-0000-00000000000a")
CASE_B = UUID("00000000-0000-0000-0000-00000000000b")
TX_A, TX_B = "T-SMOKE-A", "T-SMOKE-B"

Session = async_sessionmaker(engine, expire_on_commit=False)


def _tx(tx_id: str) -> Transaction:
    return Transaction(
        transaction_id=tx_id,
        customer_id="CU-002",
        amount=Decimal("9500.00"),
        currency="PEN",
        country="PE",
        channel=Channel.MOBILE,
        device_id="D-02",
        timestamp=datetime(2025, 12, 17, 23, 45, tzinfo=UTC),
        merchant_id="M-002",
    )


async def limpiar(session) -> None:
    # El ON DELETE CASCADE de Postgres arrastra decisions/signals/human_resolutions.
    await session.execute(delete(Case).where(Case.case_id.in_([CASE_A, CASE_B])))
    await session.execute(delete(Transaction).where(Transaction.transaction_id.in_([TX_A, TX_B])))
    await session.commit()


async def sembrar(session) -> None:
    snapshot = CustomerBehaviorIn(
        customer_id="CU-002",
        usual_amount_avg=Decimal("1200.00"),
        usual_hour_start=9,
        usual_hour_end=22,
        usual_countries=["pe"],          # minúscula a propósito: debe salir "PE"
        usual_devices=["D-02"],
    ).model_dump(mode="json")            # <- la regla del JSONB

    caso_a = Case(
        case_id=CASE_A,
        transaction=_tx(TX_A),
        status=CaseStatus.RESOLVED,
        customer_snapshot=snapshot,
    )
    caso_a.decision = Decision(
        decision=DecisionType.ESCALATE_TO_HUMAN,
        confidence=0.42,
        citations_internal=[
            InternalCitation(policy_id="FP-01", chunk_id="1", version="2025.1")
            .model_dump(mode="json")
        ],
        citations_external=[
            ExternalCitation(
                url="https://example.com/alerta-merchant",
                summary="Alerta de fraude reciente en el merchant",
                retrieved_at=datetime.now(UTC),
            ).model_dump(mode="json")
        ],
        debate_pro_fraud="Monto 8x el promedio habitual y fuera del horario del cliente.",
        debate_pro_customer="Historial limpio y dispositivo habitual conocido.",
        agent_route=["context", "behavioral", "rag", "web", "aggregation", "debate", "arbiter"],
        explanation_customer="La transacción requiere validación adicional.",
        explanation_audit="Se aplicó FP-01 y se detectó alerta externa.",
    )
    caso_a.decision.signals = [
        Signal(code="AMOUNT_OUT_OF_RANGE", description="Monto fuera de rango", severity=Severity.HIGH),
        Signal(code="UNUSUAL_HOUR", description="Horario no habitual", severity=Severity.MEDIUM),
    ]
    caso_a.human_resolution = HumanResolution(
        action=HumanAction.APPROVE, analyst_id="AN-07", notes="Verificado por teléfono."
    )

    caso_b = Case(
        case_id=CASE_B,
        transaction=_tx(TX_B),
        status=CaseStatus.ANALYZING,
        customer_snapshot=None,          # cliente nuevo, sin perfil
    )

    session.add_all([caso_a, caso_b])
    await session.commit()


async def leer(session) -> None:
    for case_id, etiqueta in ((CASE_A, "COMPLETO"), (CASE_B, "MÍNIMO")):
        case = await session.get(Case, case_id)
        assert case is not None, f"no se encontró {case_id}"
        print(f"\n===== CaseDetail ({etiqueta}) =====")
        print(CaseDetail.model_validate(case).model_dump_json(indent=2))
        print(f"----- CaseSummary ({etiqueta}) -----")
        print(CaseSummary.from_case(case).model_dump_json(indent=2))


async def main() -> None:
    async with Session() as session:
        await limpiar(session)
        await sembrar(session)
    async with Session() as session:     # sesión NUEVA: lectura real desde Postgres
        await leer(session)
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
