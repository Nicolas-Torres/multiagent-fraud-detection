"""Smoke test de la degradacion ante la caida de un agente.

Responde tres preguntas, en orden de dependencia:

    1. ¿Todos los nodos de evidencia estan decorados?
    2. ¿Que pasa SIN el decorador?  (la razon de existir de todo esto)
    3. ¿Que pasa CON el decorador en el grafo real?

    uv run python scripts/smoke_degradation.py
"""

import asyncio
import operator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from multiagent_fraud_detection.enums import Channel

from multiagent_fraud_detection.graph import builder as builder_mod
from multiagent_fraud_detection.graph import nodes as nodes_mod
from multiagent_fraud_detection.graph.nodes import (
    AGGREGATE,
    BEHAVIORAL,
    CONTEXT,
    POLICY_RAG,
    PRO_CUSTOMER,
    PRO_FRAUD,
    THREAT_INTEL,
    degrades,
)
from multiagent_fraud_detection.schemas.transaction import TransactionIn

# Nodos que deben degradar en vez de lanzar: si fallan, todavia hay decision.
# Arbiter, Explainability y el persistidor NO estan aqui a proposito: sin
# ellos no hay caso, asi que lanzan y el background task escribe FAILED.
NODOS_QUE_DEGRADAN = {
    CONTEXT: "transaction_context",
    BEHAVIORAL: "behavioral_pattern",
    THREAT_INTEL: "external_threat_intel",
    POLICY_RAG: "internal_policy_rag",
    AGGREGATE: "evidence_aggregation",
    PRO_FRAUD: "debate_pro_fraud",
    PRO_CUSTOMER: "debate_pro_customer",
}


def _transaccion() -> TransactionIn:
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


def verificar_cobertura_del_decorador() -> None:
    """Atrapa el olvido de @degrades al agregar un agente nuevo."""
    for agente, nombre_fn in NODOS_QUE_DEGRADAN.items():
        fn = getattr(nodes_mod, nombre_fn)
        marca = getattr(fn, "degrades_as", None)
        assert marca == agente, f"{nombre_fn} no esta decorado con @degrades({agente})"
    print(f"  ok - los {len(NODOS_QUE_DEGRADAN)} nodos de evidencia estan decorados")


# --- 2. El contrafactual: por que el decorador no es opcional ---


class _MiniState(TypedDict, total=False):
    acc: Annotated[list[str], operator.add]


async def _aporta(state: _MiniState) -> dict:
    return {"acc": ["aporte"]}


async def _explota(state: _MiniState) -> dict:
    raise RuntimeError("nodo sin decorar")


async def verificar_atomicidad_del_superstep() -> None:
    """Un grafo minimo, ajeno a nuestra topologia, para aislar el hecho:
    si un nodo de un superstep paralelo lanza, se pierden tambien los
    aportes de sus hermanos y el grafo entero aborta."""
    builder = StateGraph(_MiniState)
    builder.add_node("sano_a", _aporta)
    builder.add_node("sano_b", _aporta)
    builder.add_node("roto", _explota)
    for nodo in ("sano_a", "sano_b", "roto"):
        builder.add_edge(START, nodo)
        builder.add_edge(nodo, END)

    try:
        estado = await builder.compile().ainvoke({})
    except RuntimeError:
        print("  ok - sin decorador el superstep aborta y se pierden los hermanos")
        return
    raise AssertionError(f"se esperaba que abortara; devolvio {estado}")


# --- 3. El caso real: el mismo fallo, decorado ---


async def verificar_degradacion_en_el_grafo() -> None:
    @degrades(THREAT_INTEL)
    async def threat_intel_caido(state):
        raise ConnectionError("timeout del proveedor de inteligencia externa")

    original = builder_mod.external_threat_intel
    builder_mod.external_threat_intel = threat_intel_caido
    try:
        estado = await builder_mod.build_graph().ainvoke(
            {"case_id": uuid4(), "transaction": _transaccion()}
        )
    finally:
        builder_mod.external_threat_intel = original

    errores = estado.get("agent_errors", [])
    assert len(errores) == 1, f"se esperaba 1 error, hubo {len(errores)}"
    assert errores[0].agent == THREAT_INTEL
    assert errores[0].error_type == "ConnectionError"
    print(f"  ok - la falla llego como evidencia: {errores[0].agent}"
          f" / {errores[0].error_type}")

    codigos = [s.code for s in estado["signals"]]
    assert len(codigos) == 2, f"los hermanos perdieron su aporte: {codigos}"
    print(f"  ok - los hermanos del superstep conservaron sus {len(codigos)} senales")

    ruta = estado["agent_route"]
    assert THREAT_INTEL in ruta, "el agente caido debe figurar en el audit trail"
    assert ruta[-1] == "persist_decision", f"el grafo no llego al final: {ruta[-1]}"
    print(f"  ok - el grafo completo los {len(ruta)} nodos y el caido quedo en la ruta")

    assert estado["decision"], "sin decision, la degradacion no sirvio de nada"
    print(f"  ok - hubo decision degradada: {estado['decision']}")


async def main() -> None:
    print("1. cobertura del decorador")
    verificar_cobertura_del_decorador()
    print("2. contrafactual: sin decorador")
    await verificar_atomicidad_del_superstep()
    print("3. degradacion en el grafo real")
    print("   (el traceback en stderr es el logger del decorador, no una falla)")
    await verificar_degradacion_en_el_grafo()


if __name__ == "__main__":
    asyncio.run(main())
