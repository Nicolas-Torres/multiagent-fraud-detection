"""Nodos del grafo.

Stubs: cada uno escribe una constante en su clave y registra su paso. Se
reemplazan de a uno; la firma y el contrato de retorno ya son los definitivos.

Un nodo devuelve SOLO las claves que escribe. Para las claves con reducer
(zona 2 del estado) devuelve solo su aporte, nunca la lista acumulada.
"""

import logging
from collections.abc import Awaitable, Callable
from functools import wraps

from langgraph.runtime import Runtime
from sqlalchemy import delete, update

from multiagent_fraud_detection.db.models import AgentError as AgentErrorRow
from multiagent_fraud_detection.db.models import Case, Decision, Signal
from multiagent_fraud_detection.enums import CaseStatus, DecisionType, Severity
from multiagent_fraud_detection.graph.context import GraphContext
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

        # Marca estructural: permite afirmar en un test que ningun nodo de
        # evidencia quedo sin decorar al agregarse.
        wrapper.degrades_as = agent
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


def _verificar_invariantes(state: GraphState) -> None:
    """Guardas, no reparaciones: si alguna dispara, el Arbiter tiene un bug.

    Una guarda que repara esconde el bug. Estas levantan, y el wrapper del
    background task escribe FAILED.
    """
    decision = state["decision"]
    base = state.get("base_confidence")

    if decision is not DecisionType.ESCALATE_TO_HUMAN:
        # Diferir a un humano no es un veredicto: por eso queda exento. Sin la
        # excepcion, un caso sin citas no tendria ninguna salida posible.
        if not state.get("citations_internal"):
            raise ValueError("veredicto autonomo sin respaldo interno")
        if base is None:
            raise ValueError("veredicto autonomo sin score deterministico")

    if base is not None and state["confidence"] != base and not state.get(
        "confidence_rationale"
    ):
        raise ValueError("el Arbiter ajusto la confianza sin justificarlo")


async def persist_decision(
    state: GraphState, runtime: Runtime[GraphContext]
) -> dict:
    """Unico punto donde el grafo escribe a las tablas.

    Semantica de **reemplazo del agregado**: el resultado de este nodo para
    este caso es exactamente esto, no "asegurate de que estas filas existan".
    Un reintento sustituye, no complementa.

    La clave de idempotencia es `case_id`, que ya es PK de `decisions`; el
    `ON DELETE CASCADE` barre `signals` y `agent_errors` sin nombrarlas.
    """
    _verificar_invariantes(state)

    case_id = state["case_id"]
    decision = state["decision"]
    estado = (
        CaseStatus.PENDING_HUMAN
        if decision is DecisionType.ESCALATE_TO_HUMAN
        else CaseStatus.DECIDED
    )

    async with runtime.context.session_factory() as session:
        async with session.begin():
            # delete() de Core y no un borrado por objeto: con lazy="selectin"
            # el ORM cargaria los hijos para borrarlos uno por uno en vez de
            # dejar que la cascada de la BD haga su trabajo.
            await session.execute(
                delete(Decision).where(Decision.case_id == case_id)
            )

            session.add(
                Decision(
                    case_id=case_id,
                    decision=decision,
                    confidence=state["confidence"],
                    risk_score=state.get("risk_score"),
                    base_confidence=state.get("base_confidence"),
                    confidence_rationale=state.get("confidence_rationale"),
                    scoring_version=state.get("scoring_version"),
                    # model_dump(mode="json"): en modo Python, HttpUrl y
                    # datetime no son serializables por psycopg.
                    citations_internal=[
                        c.model_dump(mode="json")
                        for c in state.get("citations_internal", [])
                    ],
                    citations_external=[
                        c.model_dump(mode="json")
                        for c in state.get("citations_external", [])
                    ],
                    debate_pro_fraud=state.get("pro_fraud_argument", ""),
                    debate_pro_customer=state.get("pro_customer_argument", ""),
                    agent_route=state.get("agent_route", []),
                    explanation_customer=state.get("explanation_customer", ""),
                    explanation_audit=state.get("explanation_audit", ""),
                    signals=[
                        # `emitted_by` no cruza: el contrato define Signal sin
                        # procedencia expuesta al cliente.
                        Signal(
                            case_id=case_id,
                            code=s.code,
                            description=s.description,
                            severity=s.severity,
                        )
                        for s in state.get("signals", [])
                    ],
                    agent_errors=[
                        AgentErrorRow(
                            case_id=case_id,
                            agent=e.agent,
                            error_type=e.error_type,
                            message=e.message,
                            occurred_at=e.occurred_at,
                        )
                        for e in state.get("agent_errors", [])
                    ],
                )
            )

            await session.execute(
                update(Case).where(Case.case_id == case_id).values(status=estado)
            )

    # No se agrega a `agent_route`: ese campo es el rastro de los AGENTES, y
    # este nodo es la costura con la base. Que corrio lo prueba la fila, no
    # una cadena en una lista.
    return {}
