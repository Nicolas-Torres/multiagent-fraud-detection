"""Cableado del grafo.

Topologia derivada de las dependencias de datos: dos nodos van en paralelo si
y solo si ninguno lee lo que el otro escribe.

    START -> [context | behavioral | threat_intel] -> rag -> aggregate
          -> [pro_fraud | pro_customer] -> arbiter -> explain -> persist -> END

Cero aristas condicionales: DECIDED vs PENDING_HUMAN es un valor de `status`
que escribe el nodo de persistencia, no una bifurcacion del grafo.
"""

from langgraph.graph import END, START, StateGraph

from agents.src.graph.nodes import (
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
    behavioral_pattern,
    debate_pro_customer,
    debate_pro_fraud,
    decision_arbiter,
    evidence_aggregation,
    explainability,
    external_threat_intel,
    internal_policy_rag,
    persist_decision,
    transaction_context,
)
from agents.src.graph.context import GraphContext
from agents.src.graph.state import GraphInput, GraphState


def build_graph():
    """Sin `output_schema`: nadie lee el retorno del grafo. El dashboard hace
    polling contra las tablas, que escribe el nodo de persistencia.

    Sin checkpointer: no hay `interrupt()`, y los nodos de evidencia capturan
    su propia falla. Solo cubriria la muerte del proceso, que sale mas barato
    con una consulta sobre casos estancados en ANALYZING.
    """
    builder = StateGraph(
        GraphState,
        context_schema=GraphContext,
        input_schema=GraphInput
    )

    builder.add_node(CONTEXT, transaction_context)
    builder.add_node(BEHAVIORAL, behavioral_pattern)
    builder.add_node(THREAT_INTEL, external_threat_intel)
    builder.add_node(POLICY_RAG, internal_policy_rag)
    builder.add_node(AGGREGATE, evidence_aggregation)
    builder.add_node(PRO_FRAUD, debate_pro_fraud)
    builder.add_node(PRO_CUSTOMER, debate_pro_customer)
    builder.add_node(ARBITER, decision_arbiter)
    builder.add_node(EXPLAIN, explainability)
    builder.add_node(PERSIST, persist_decision)

    # Ola 1: tres aristas desde START = fan-out.
    for node in (CONTEXT, BEHAVIORAL, THREAT_INTEL):
        builder.add_edge(START, node)
        # Fan-in: el RAG corre cuando los tres terminaron. No hace falta
        # `defer=True` porque las tres ramas son de un solo nodo.
        builder.add_edge(node, POLICY_RAG)

    builder.add_edge(POLICY_RAG, AGGREGATE)

    # Ola 2: el debate no necesita reducer porque cada rama escribe su
    # propia clave.
    for node in (PRO_FRAUD, PRO_CUSTOMER):
        builder.add_edge(AGGREGATE, node)
        builder.add_edge(node, ARBITER)

    builder.add_edge(ARBITER, EXPLAIN)
    builder.add_edge(EXPLAIN, PERSIST)
    builder.add_edge(PERSIST, END)

    return builder.compile()
