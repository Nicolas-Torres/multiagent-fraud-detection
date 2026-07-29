"""Nodos del grafo.

Stubs: cada uno escribe una constante en su clave y registra su paso. Se
reemplazan de a uno; la firma y el contrato de retorno ya son los definitivos.

Un nodo devuelve SOLO las claves que escribe. Para las claves con reducer
(zona 2 del estado) devuelve solo su aporte, nunca la lista acumulada.
"""

import logging
from collections.abc import Awaitable, Callable
from functools import wraps

from multiagent_fraud_detection.enums import DecisionType, Severity
from multiagent_fraud_detection.graph.state import AgentError, GraphState, WorkingSignal

logger = logging.getLogger(__name__)

# Nombres de nodo como constantes: los consumen el builder y `agent_route`,
# y un typo entre ambos produce un grafo que compila y no corre.
CONTEXT = "transaction_context"
BEHAVIORAL = "behavioral_pattern"
THREAT_INTEL = "external_threat_intel"
POLICY_RAG = "internal_policy_rag"
AGGREGATE = "evidence_aggregation"
PRO_FRAUD = "debate_pro_fraud"
PRO_CUSTOMER = "debate_pro_customer"
ARBITER = "decision_arbiter"
EXPLAIN = "explainability"
PERSIST = "persist_decision"

NodeFn = Callable[[GraphState], Awaitable[dict]]


def degrades(agent: str) -> Callable[[NodeFn], NodeFn]:
    """Convierte una falla del nodo en evidencia en vez de en una excepcion.

    Obligatorio en los nodos de evidencia: si un nodo de un superstep paralelo
    lanza, se pierden tambien los resultados de sus hermanos del mismo
    superstep. Capturar aqui es lo que hace real la degradacion.

    Incompatible con RetryPolicy de LangGraph (que solo dispara ante una
    excepcion que salga del nodo): el reintento va adentro del cuerpo.
    """

    def decorator(fn: NodeFn) -> NodeFn:
        @wraps(fn)
        async def wrapper(state: GraphState) -> dict:
            try:
                return await fn(state)
            except Exception as exc:  # noqa: BLE001 - el punto es no propagar
                logger.exception("nodo %s degradado", agent)
                return {
                    "agent_route": [agent],
                    "agent_errors": [
                        AgentError(
                            agent=agent,
                            error_type=type(exc).__name__,
                            message=str(exc),
                        )
                    ],
                }

        return wrapper

    return decorator


# --- Ola 1: independientes entre si ---


@degrades(CONTEXT)
async def transaction_context(state: GraphState) -> dict:
    return {
        "agent_route": [CONTEXT],
        "signals": [
            WorkingSignal(
                code="STUB_ABSOLUTE",
                description="stub: senal leida de la transaccion sola",
                severity=Severity.LOW,
                emitted_by=CONTEXT,
            )
        ],
    }


@degrades(BEHAVIORAL)
async def behavioral_pattern(state: GraphState) -> dict:
    # El stub simula el caso interesante: cliente sin perfil previo.
    # `customer_snapshot=None` NO comunica eso; la senal si.
    return {
        "agent_route": [BEHAVIORAL],
        "customer_snapshot": None,
        "signals": [
            WorkingSignal(
                code="NO_CUSTOMER_PROFILE",
                description="stub: el cliente no tiene perfil de comportamiento",
                severity=Severity.MEDIUM,
                emitted_by=BEHAVIORAL,
            )
        ],
    }


@degrades(THREAT_INTEL)
async def external_threat_intel(state: GraphState) -> dict:
    return {"agent_route": [THREAT_INTEL], "citations_external": [], "discarded_sources": []}


# --- Ola 2 ---


@degrades(POLICY_RAG)
async def internal_policy_rag(state: GraphState) -> dict:
    # Aqui se arma la query hibrida: senales ya detectadas + descriptor minimo
    # de la transaccion. Por eso este nodo va despues de la ola 1.
    _ = state.get("signals", [])
    return {"agent_route": [POLICY_RAG], "citations_internal": [], "rag_chunks": []}


@degrades(AGGREGATE)
async def evidence_aggregation(state: GraphState) -> dict:
    # Cuatro trabajos reales: deduplicar por `code` usando `emitted_by`,
    # descartar lo que no paso el allowlist, ORDENAR de forma determinista
    # (el orden entre ramas paralelas es arbitrario) y calcular el score.
    return {"agent_route": [AGGREGATE], "base_confidence": 0.5}


@degrades(PRO_FRAUD)
async def debate_pro_fraud(state: GraphState) -> dict:
    return {"agent_route": [PRO_FRAUD], "pro_fraud_argument": "stub"}


@degrades(PRO_CUSTOMER)
async def debate_pro_customer(state: GraphState) -> dict:
    return {"agent_route": [PRO_CUSTOMER], "pro_customer_argument": "stub"}


# --- Nodos fatales: si fallan no hay caso, asi que lanzan ---


async def decision_arbiter(state: GraphState) -> dict:
    # Sin `citations_internal` no puede emitir veredicto autonomo: degrada a
    # ESCALATE_TO_HUMAN. La ausencia de respaldo es la razon para llamar al humano.
    return {
        "agent_route": [ARBITER],
        "decision": DecisionType.ESCALATE_TO_HUMAN,
        "confidence": state.get("base_confidence", 0.0),
        "confidence_rationale": "stub",
    }


async def explainability(state: GraphState) -> dict:
    return {
        "agent_route": [EXPLAIN],
        "explanation_customer": "stub",
        "explanation_audit": "stub",
    }


async def persist_decision(state: GraphState) -> dict:
    # Reemplazo del agregado: DELETE por case_id (la cascada barre signals) +
    # INSERT, todo en una transaccion. Con la guarda del invariante de citacion.
    return {"agent_route": [PERSIST]}