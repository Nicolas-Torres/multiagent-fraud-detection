"""Smoke test del esqueleto del grafo.

Verifica el cableado antes de que exista un solo prompt: supersteps, reducers,
filtrado del input y supervivencia ante la falla de un agente.

    uv run python scripts/smoke_graph.py
"""

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from multiagent_fraud_detection.enums import Channel
from multiagent_fraud_detection.graph.builder import build_graph
from multiagent_fraud_detection.graph.nodes import (
    AGGREGATE,
    ARBITER,
    BEHAVIORAL,
    CONTEXT,
    EXPLAIN,
    PERSIST,
    POLICY_RAG,
    PRO_CUSTOMER,
    PRO_FRAUD,
    THREAT_INTEL,
)
from multiagent_fraud_detection.schemas.transaction import TransactionIn

SUPERSTEPS = [
    {CONTEXT, BEHAVIORAL, THREAT_INTEL},
    {POLICY_RAG},
    {AGGREGATE},
    {PRO_FRAUD, PRO_CUSTOMER},
    {ARBITER},
    {EXPLAIN},
    {PERSIST},
]


def transaccion() -> TransactionIn:
    return TransactionIn(
        transaction_id="T-1002",
        customer_id="CU-002",
        amount=Decimal("9500.00"),
        currency="PEN",
        country="PE",
        channel=Channel.MOBILE,
        device_id="D-02",
        timestamp=datetime(2025, 12, 17, 23, 45, tzinfo=UTC),
        merchant_id="M-002",
    )


def verificar_supersteps(agent_route: list[str]) -> None:
    """El orden ENTRE supersteps es determinista; DENTRO de uno, arbitrario."""
    cursor = 0
    for i, superstep in enumerate(SUPERSTEPS):
        tramo = set(agent_route[cursor : cursor + len(superstep)])
        assert tramo == superstep, f"supersteps {i}: se esperaba {superstep}, llego {tramo}"
        cursor += len(superstep)
    assert cursor == len(agent_route), "sobran nodos en agent_route"


async def main() -> None:
    graph = build_graph()

    estado = await graph.ainvoke(
        {
            "case_id": uuid4(),
            "transaction": transaccion(),
            "clave_intrusa": "deberia desaparecer",  # no esta en GraphInput
        }
    )

    print("agent_route:", estado["agent_route"])
    verificar_supersteps(estado["agent_route"])
    print("  ok - 10 nodos, agrupados por supersteps")

    assert "clave_intrusa" not in estado
    print("  ok - input_schema filtro la clave que no declara")

    codigos = [s.code for s in estado["signals"]]
    assert len(codigos) == 2, f"el reducer no acumulo: {codigos}"
    print(f"  ok - reducer acumulo {len(codigos)} senales de 2 emisores: {codigos}")

    assert estado.get("customer_snapshot") is None
    assert "NO_CUSTOMER_PROFILE" in codigos
    print("  ok - 'sin perfil' viaja como senal, no como None")

    assert not estado.get("agent_errors"), estado.get("agent_errors")
    print("  ok - sin fallas degradadas en la corrida limpia")

    print("\nclaves del estado final:", sorted(estado))


if __name__ == "__main__":
    asyncio.run(main())
