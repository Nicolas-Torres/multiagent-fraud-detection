"""Smoke test del esqueleto del grafo.

Verifica el cableado antes de que exista un solo prompt: supersteps, reducers,
filtrado del input y persistencia del resultado.

    uv run python scripts/smoke_graph.py
"""

import asyncio
import sys
from uuid import UUID

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from sqlalchemy import select

from _fixtures import CONTEXTO, limpiar, sembrar, transaccion
from src.db.models import Case, Decision
from src.db.session import AsyncSessionLocal
from src.enums import CaseStatus
from src.graph.builder import build_graph
from src.graph.nodes import (
    AGGREGATE,
    ARBITER,
    BEHAVIORAL,
    CONTEXT,
    EXPLAIN,
    POLICY_RAG,
    PRO_CUSTOMER,
    PRO_FRAUD,
    THREAT_INTEL,
)

CASE_ID = UUID("00000000-0000-0000-0000-0000000000c1")
TX_ID = "T-SMOKE-GRAPH"

# Los nueve nodos de AGENTE, agrupados por superstep. `persist_decision` no
# figura: no es un agente y no se registra en `agent_route`. Que corrio lo
# prueba la fila en `decisions`, que es una afirmacion mas fuerte.
SUPERSTEPS = [
    {CONTEXT, BEHAVIORAL, THREAT_INTEL},
    {POLICY_RAG},
    {AGGREGATE},
    {PRO_FRAUD, PRO_CUSTOMER},
    {ARBITER},
    {EXPLAIN},
]


def verify_supersteps(agent_route: list[str]) -> None:
    """El orden ENTRE supersteps es determinista; DENTRO de uno, arbitrario."""
    cursor = 0
    for i, superstep in enumerate(SUPERSTEPS):
        tramo = set(agent_route[cursor : cursor + len(superstep)])
        assert tramo == superstep, f"superstep {i}: esperaba {superstep}, llego {tramo}"
        cursor += len(superstep)
    assert cursor == len(agent_route), f"sobran nodos en agent_route: {agent_route}"


async def main() -> None:
    await sembrar(CASE_ID, TX_ID)
    graph = build_graph()

    estado = await graph.ainvoke(
        {
            "case_id": CASE_ID,
            "transaction": transaccion(TX_ID),
            "clave_intrusa": "deberia desaparecer",  # no esta en GraphInput
        },
        context=CONTEXTO,
    )

    print("agent_route:", estado["agent_route"])
    verify_supersteps(estado["agent_route"])
    print("  ok - 9 nodos de agente, agrupados por superstep")

    assert "clave_intrusa" not in estado
    print("  ok - input_schema filtro la clave que no declara")

    codigos = [s.code for s in estado["signals"]]
    assert len(codigos) >= 1, f"el reducer no acumulo: {codigos}"
    print(f"  ok - el reducer acumulo {len(codigos)} senal(es) de la ola 1: {codigos}")

    assert estado.get("customer_snapshot") is None
    assert "NO_CUSTOMER_PROFILE" in codigos
    print("  ok - 'sin perfil' viaja como senal, no como None")

    # Evidence Aggregation deduplica y ordena en `final_signals`; no vuelve a
    # `signals` (que tiene reducer y duplicaria en silencio, repaso 03 §2.2).
    finales = estado.get("final_signals", estado["signals"])
    assert len(finales) == len({s.code for s in finales}), "hay senales duplicadas"
    print(f"  ok - Evidence Aggregation dejo {len(finales)} senal(es) sin duplicados")

    assert not estado.get("agent_errors"), estado.get("agent_errors")
    print("  ok - sin fallas degradadas en la corrida limpia")

    async with AsyncSessionLocal() as session:
        decision = (
            await session.execute(select(Decision).where(Decision.case_id == CASE_ID))
        ).scalar_one()
        status = (
            await session.execute(select(Case.status).where(Case.case_id == CASE_ID))
        ).scalar_one()

    assert decision.agent_route == estado["agent_route"], "memoria y BD divergen"
    assert len(decision.signals) == len(finales), "lo persistido difiere de lo agregado"
    assert status is CaseStatus.PENDING_HUMAN
    print(f"  ok - persistido: {len(decision.signals)} senal(es), status={status.value}")

    await limpiar(CASE_ID, TX_ID)
    print("\nclaves del estado final:", sorted(estado))


if __name__ == "__main__":
    asyncio.run(main())
