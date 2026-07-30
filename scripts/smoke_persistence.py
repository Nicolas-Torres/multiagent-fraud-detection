"""Smoke test del nodo persistidor.

La pregunta que responde: **un reintento, ¿duplica?** Importa porque el
`signals.id` es BIGSERIAL sin UNIQUE, asi que una segunda escritura no chocaria
con nada: duplicaria en silencio y envenenaria justo lo que el harness del
entregable 7 mide.

    uv run python scripts/smoke_persistence.py
"""

import asyncio
import sys
from uuid import UUID

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from langgraph.runtime import Runtime
from sqlalchemy import func, select

from _fixtures import CONTEXTO, limpiar, sembrar
from multiagent_fraud_detection.db.models import AgentError as AgentErrorRow
from multiagent_fraud_detection.db.models import Case, Decision, Signal
from multiagent_fraud_detection.db.session import AsyncSessionLocal
from multiagent_fraud_detection.enums import CaseStatus, DecisionType, Severity
from multiagent_fraud_detection.graph.nodes import persist_decision
from multiagent_fraud_detection.graph.state import AgentError, WorkingSignal
from multiagent_fraud_detection.schemas.decision import InternalCitation

CASE_ID = UUID("00000000-0000-0000-0000-0000000000f1")
TX_ID = "T-SMOKE-PERSIST"

RUNTIME = Runtime(context=CONTEXTO)


def estado(**cambios) -> dict:
    """Un veredicto autonomo completo, con los invariantes satisfechos."""
    base = dict(
        case_id=CASE_ID,
        decision=DecisionType.BLOCK,
        confidence=0.9,
        risk_score=0.88,
        base_confidence=0.9,
        scoring_version="2026.1",
        citations_internal=[
            InternalCitation(policy_id="FP-01", chunk_id="1", version="2025.1")
        ],
        citations_external=[],
        pro_fraud_argument="monto y horario anomalos",
        pro_customer_argument="historial limpio",
        agent_route=["transaction_context", "behavioral_pattern"],
        explanation_customer="requiere validacion",
        explanation_audit="se aplico FP-01",
        signals=[
            WorkingSignal(code="AMOUNT_OUT_OF_RANGE", description="7.9x el promedio",
                          severity=Severity.HIGH, emitted_by="behavioral_pattern"),
            WorkingSignal(code="UNUSUAL_HOUR", description="23:45 fuera de 09-22",
                          severity=Severity.LOW, emitted_by="transaction_context"),
        ],
        agent_errors=[
            AgentError(agent="external_threat_intel",
                       error_type="ConnectionError", message="timeout")
        ],
    )
    base.update(cambios)
    return base


async def contar() -> tuple[int, int, int, CaseStatus | None]:
    """Filtrado por CASE_ID: un test no es dueno de la base.

    Contar filas globalmente lo volveria dependiente del orden de ejecucion y
    de lo que otros smoke tests dejaron atras.
    """
    async with AsyncSessionLocal() as s:
        return (
            (await s.execute(
                select(func.count()).select_from(Decision)
                .where(Decision.case_id == CASE_ID)
            )).scalar(),
            (await s.execute(
                select(func.count()).select_from(Signal)
                .where(Signal.case_id == CASE_ID)
            )).scalar(),
            (await s.execute(
                select(func.count()).select_from(AgentErrorRow)
                .where(AgentErrorRow.case_id == CASE_ID)
            )).scalar(),
            (await s.execute(
                select(Case.status).where(Case.case_id == CASE_ID)
            )).scalar(),
        )


async def main() -> None:
    await sembrar(CASE_ID, TX_ID)

    print("1. primera escritura")
    await persist_decision(estado(), RUNTIME)
    d, sg, ae, st = await contar()
    assert (d, sg, ae) == (1, 2, 1), (d, sg, ae)
    assert st is CaseStatus.DECIDED
    print(f"  ok - decisions={d} signals={sg} agent_errors={ae} status={st.value}")

    print("2. reintento del mismo nodo")
    await persist_decision(estado(), RUNTIME)
    d, sg, ae, _ = await contar()
    assert (d, sg, ae) == (1, 2, 1), f"el reintento duplico: {(d, sg, ae)}"
    print(f"  ok - sigue en decisions={d} signals={sg} agent_errors={ae}")

    print("3. reintento con senales distintas")
    await persist_decision(
        estado(signals=[WorkingSignal(code="NEW_DEVICE", description="D-99 desconocido",
                                      severity=Severity.MEDIUM, emitted_by="behavioral_pattern")]),
        RUNTIME,
    )
    async with AsyncSessionLocal() as s:
        codigos = (await s.execute(
            select(Signal.code).where(Signal.case_id == CASE_ID)
        )).scalars().all()
    assert codigos == ["NEW_DEVICE"], codigos
    print(f"  ok - reemplazo del agregado, no union: {codigos}")

    print("4. escalado a humano")
    await persist_decision(
        estado(decision=DecisionType.ESCALATE_TO_HUMAN, citations_internal=[],
               risk_score=None, base_confidence=None, scoring_version=None),
        RUNTIME,
    )
    _, _, _, st = await contar()
    async with AsyncSessionLocal() as s:
        dec = (await s.execute(select(Decision).where(Decision.case_id == CASE_ID))).scalar_one()
    assert st is CaseStatus.PENDING_HUMAN
    assert dec.base_confidence is None and dec.scoring_version is None
    print(f"  ok - status={st.value}, sin citas ni score (exento del invariante)")

    print("5. las guardas levantan")
    casos = [
        ("veredicto autonomo sin citas internas", estado(citations_internal=[])),
        ("veredicto autonomo sin score deterministico", estado(base_confidence=None)),
        ("ajuste de confianza sin justificacion", estado(confidence=0.7)),
    ]
    for nombre, mal in casos:
        try:
            await persist_decision(mal, RUNTIME)
        except ValueError as exc:
            print(f"  ok - {nombre}: {exc}")
        else:
            raise AssertionError(f"'{nombre}' no levanto")

    await limpiar(CASE_ID, TX_ID)
    d, sg, ae, _ = await contar()
    assert (d, sg, ae) == (0, 0, 0), f"la cascada no limpio: {(d, sg, ae)}"
    print("\n  ok - borrar el caso arrastro decision, senales y errores")


if __name__ == "__main__":
    asyncio.run(main())
