"""Nodos del grafo.

Stubs: cada uno escribe una constante en su clave y registra su paso. Se
reemplazan de a uno; la firma y el contrato de retorno ya son los definitivos.

Un nodo devuelve SOLO las claves que escribe. Para las claves con reducer
(zona 2 del estado) devuelve solo su aporte, nunca la lista acumulada.
"""

import inspect
import inspect
import logging
from collections.abc import Awaitable, Callable
from functools import wraps

from langgraph.runtime import Runtime
from sqlalchemy import delete, select, update

from src.db.models import AgentError as AgentErrorRow
from src.db.models import Case, CustomerBehavior, Decision, Signal
from src.db.repositories.merchant_blacklist import active_merchants
from src.db.repositories.policy_rag import buscar_politicas
from src.db.repositories.transaction_history import (
    history_for_customer,
    history_for_device,
)
from src.db.repositories.web_search_allowlist import list_allowed
from src.domain.constants import decision_desde_codigos
from src.domain.policies import (
    SIGNAL_TO_POLICY,
    PolicySignal,
    evaluate_for_transaction,
    fp07,
)
from src.domain.scoring import SCORING_VERSION, base_confidence, risk_score
from src.enums import CaseStatus, DecisionType, Severity
from src.graph.context import GraphContext
from src.graph.state import (
    AgentError,
    DiscardedSource,
    GraphState,
    RetrievedChunk,
    WorkingSignal,
)
from src.llm.prompts import (
    ARBITER_PROMPT,
    DEBATE_PRO_CLIENTE_PROMPT,
    DEBATE_PRO_FRAUDE_PROMPT,
    EXPLAIN_PROMPT,
    ArbiterOut,
    DebateOut,
    ExplainOut,
)
from src.schemas.customer_behavior import CustomerBehaviorRead
from src.schemas.decision import InternalCitation

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


def _acepta_runtime(fn: NodeFn) -> bool:
    """¿La función declara un segundo parámetro `runtime`?

    LangGraph inyecta el `Runtime` a los nodos que lo piden. Los nodos que
    leen de la base lo necesitan; los que solo combinan estado, no. El
    decorador debe respetar esa diferencia.
    """
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False
    return "runtime" in params


def degrades(agent: str) -> Callable[[NodeFn], NodeFn]:
    """Convierte una falla del nodo en evidencia en vez de en una excepcion.

    Obligatorio en los nodos de evidencia: si un nodo de un superstep paralelo
    lanza, se pierden tambien los resultados de sus hermanos del mismo
    superstep. Capturar aqui es lo que hace real la degradacion.

    Incompatible con RetryPolicy de LangGraph (que solo dispara ante una
    excepcion que salga del nodo): el reintento va adentro del cuerpo.
    """

    def decorator(fn: NodeFn) -> NodeFn:
        pasa_runtime = _acepta_runtime(fn)

        @wraps(fn)
        async def wrapper(state: GraphState, runtime=None) -> dict:
            try:
                if pasa_runtime:
                    return await fn(state, runtime)
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


# --- Helpers ---


def _working(senal: PolicySignal, emitted_by: str) -> WorkingSignal:
    """Convierte una señal de dominio a una señal en vuelo del estado."""
    return WorkingSignal(
        code=senal.code,
        description=senal.description,
        severity=senal.severity,
        emitted_by=emitted_by,
    )


async def _segment_average_usd(session) -> dict:
    """Promedio del monto habitual por segmento, en USD.

    FP-08 compara contra el promedio del segmento, no contra el del propio
    cliente (contrato §2.5). Se calcula sobre `customer_behaviors` convirtiendo
    cada `usual_amount_avg` a la moneda de referencia.
    """
    from src.domain.constants import CURRENCY_FACTOR

    filas = await session.execute(
        select(CustomerBehavior.segment, CustomerBehavior.usual_amount_avg, CustomerBehavior.currency)
    )
    acumulado: dict = {}
    for segment, monto, currency in filas:
        usd = float(monto) / float(CURRENCY_FACTOR.get(currency, 1.0))
        entry = acumulado.setdefault(segment, [0.0, 0])
        entry[0] += usd
        entry[1] += 1
    return {segment: total / conteo for segment, (total, conteo) in acumulado.items()}


# --- Ola 1: independientes entre si ---


@degrades(CONTEXT)
async def transaction_context(state: GraphState, runtime: Runtime[GraphContext]) -> dict:
    """Agent de contexto de la transacción: FP-07 (lista negra).

    Es el único agente que evalúa una política con solo la transacción y un
    dato de gobernanza: el comercio en lista negra sobre el umbral (D2).
    """
    tx = state["transaction"]
    async with runtime.context.session_factory() as session:
        comercios = await active_merchants(session)

    senales = []
    if tx.merchant_id in comercios:
        senal = fp07(tx, tx.merchant_id, tx.currency)
        if senal:
            senales.append(_working(senal, CONTEXT))

    return {"agent_route": [CONTEXT], "signals": senales}


@degrades(BEHAVIORAL)
async def behavioral_pattern(state: GraphState, runtime: Runtime[GraphContext]) -> dict:
    """Agent de patrones de comportamiento: FP-01…FP-06, FP-08, FP-09, FP-11.

    Recupera el perfil del cliente y su historial (cliente y dispositivo) con
    el invariante *as-of*, evalúa las políticas que necesitan perfil e
    historial, y congela el snapshot del perfil usado (D2, contrato §7.4).
    """
    tx = state["transaction"]

    async with runtime.context.session_factory() as session:
        perfil_row = await session.scalar(
            select(CustomerBehavior).where(
                CustomerBehavior.customer_id == tx.customer_id
            )
        )
        previas_device = await history_for_device(
            session, device_id=tx.device_id, as_of=tx.timestamp
        )
        previas_customer = await history_for_customer(
            session, customer_id=tx.customer_id, as_of=tx.timestamp
        )
        seg_avg_usd = await _segment_average_usd(session)

    if perfil_row is None:
        # `customer_snapshot=None` NO comunica "cliente sin perfil": eso lo
        # dice la señal. Sin perfil no hay políticas evaluables (contrato §2.5).
        return {
            "agent_route": [BEHAVIORAL],
            "customer_snapshot": None,
            "signals": [
                WorkingSignal(
                    code="NO_CUSTOMER_PROFILE",
                    description="el cliente no tiene perfil de comportamiento",
                    severity=Severity.MEDIUM,
                    emitted_by=BEHAVIORAL,
                )
            ],
        }

    perfil = CustomerBehaviorRead.model_validate(perfil_row)
    senales = [
        _working(s, BEHAVIORAL)
        for s in evaluate_for_transaction(
            tx,
            perfil,
            previas_device=previas_device,
            previas_customer=previas_customer,
            seg_avg_usd=seg_avg_usd,
        )
    ]

    return {
        "agent_route": [BEHAVIORAL],
        "customer_snapshot": perfil,
        "signals": senales,
    }


@degrades(THREAT_INTEL)
async def external_threat_intel(state: GraphState, runtime: Runtime[GraphContext]) -> dict:
    """Busca alertas externas de fraude solo dentro de la lista permitida.

    Gobernada (contrato §4): solo se consultan dominios de `web_search_allowlist`.
    Con `THREAT_INTEL_OFFLINE=true` (evaluación, ADR-0005) devuelve citas
    externas vacías y registra la omisión, para que el harness sea reproducible.
    """
    if runtime.context.threat_intel_offline:
        return {
            "agent_route": [THREAT_INTEL],
            "citations_external": [],
            "discarded_sources": [
                DiscardedSource(
                    url="(offline)",
                    reason="THREAT_INTEL_OFFLINE=true: búsqueda externa desactivada en evaluación",
                )
            ],
        }

    tx = state["transaction"]
    async with runtime.context.session_factory() as session:
        permitidos = await list_allowed(session)

    # Sin proveedor de búsqueda web configurado, no hay nada que consultar: se
    # degrada con citas vacías en vez de inventar fuentes.
    if not permitidos:
        return {
            "agent_route": [THREAT_INTEL],
            "citations_external": [],
            "discarded_sources": [],
        }

    # La búsqueda web real queda fuera del alcance de esta etapa: el contrato
    # la define como gobernada, pero el consumidor (FP-10) está fuera del
    # alcance (ADR-0005). El nodo respeta el allowlist y devuelve sin citas.
    _ = tx
    return {
        "agent_route": [THREAT_INTEL],
        "citations_external": [],
        "discarded_sources": [],
    }


# --- Ola 2 ---


@degrades(POLICY_RAG)
async def internal_policy_rag(state: GraphState, runtime: Runtime[GraphContext]) -> dict:
    """Recupera las políticas relevantes al caso y las cita como respaldo.

    La query es híbrida (D7 del diseño, tarea 5.4): se arma un texto con las
    señales ya detectadas + el descriptor mínimo de la transacción, se
    embedding y se recupera por similitud sobre `policy_chunks`. Sin
    embeddings configurados (evaluación offline, smoke tests) degrada con
    citas vacías: el Arbiter las trata como ausencia de respaldo.
    """
    tx = state["transaction"]
    senales = state.get("signals", [])

    if runtime.context.embeddings is None:
        logger.warning("nodo %s sin embeddings configurados; citas vacias", POLICY_RAG)
        return {"agent_route": [POLICY_RAG], "citations_internal": [], "rag_chunks": []}

    query = (
        f"Señales detectadas: {', '.join(s.code for s in senales) or 'ninguna'}.\n"
        f"Transacción: monto {tx.amount} {tx.currency}, país {tx.country}, "
        f"canal {tx.channel.value}, dispositivo {tx.device_id}, "
        f"comercio {tx.merchant_id}."
    )
    vector = await runtime.context.embeddings.aembed_query(query)

    async with runtime.context.session_factory() as session:
        chunks = await buscar_politicas(session, vector, top_k=5, min_score=0.3)

    citas = [
        InternalCitation(policy_id=chunk.policy_id, chunk_id=chunk.chunk_id, version=chunk.version)
        for chunk, _ in chunks
    ]
    recuperados = [
        RetrievedChunk(
            policy_id=chunk.policy_id,
            chunk_id=chunk.chunk_id,
            version=chunk.version,
            content=chunk.content,
            score=score,
        )
        for chunk, score in chunks
    ]

    return {
        "agent_route": [POLICY_RAG],
        "citations_internal": citas,
        "rag_chunks": recuperados,
    }


@degrades(AGGREGATE)
async def evidence_aggregation(state: GraphState) -> dict:
    """Fusiona la evidencia de la ola 1 en una lista determinística.

    Tres trabajos reales:
      1. Deduplicar señales por `code`. `emitted_by` identifica redundancias:
         si dos agentes emiten la misma señal, se conserva una.
      2. Ordenar de forma determinista: el orden entre ramas paralelas es
         arbitrario, y el contrato exige un criterio fijo y documentado
         (§2.5).
      3. Calcular `risk_score` y `base_confidence` determinísticos.
    """
    senales = state.get("signals", [])

    # Deduplicar por `code`, conservando el primer emisor. Las señales en vuelo
    # llevan `emitted_by` justamente para esto.
    unicas: dict[str, WorkingSignal] = {}
    for s in senales:
        unicas.setdefault(s.code, s)

    # Orden determinístico: por código. Es reproducible entre corridas y no
    # depende del orden de llegada de las ramas paralelas.
    ordenadas = sorted(unicas.values(), key=lambda s: s.code)

    degradado = bool(state.get("agent_errors"))
    riesgo = risk_score(ordenadas)
    confianza = base_confidence(riesgo, degraded=degradado)

    return {
        "agent_route": [AGGREGATE],
        "final_signals": ordenadas,
        "risk_score": riesgo,
        "base_confidence": confianza,
        "scoring_version": SCORING_VERSION,
    }


def _formatear_evidencia(state: GraphState) -> str:
    """Texto de la evidencia agregada para los prompts de los agentes con LLM."""
    tx = state["transaction"]
    senales = state.get("signals", [])
    lineas = [
        f"Transacción: {tx.transaction_id} · monto {tx.amount} {tx.currency} · "
        f"país {tx.country} · canal {tx.channel.value} · dispositivo "
        f"{tx.device_id} · comercio {tx.merchant_id} · {tx.timestamp.isoformat()}",
        "Señales detectadas:",
    ]
    if senales:
        lineas += [
            f"  - {s.code} [{s.severity.value}]: {s.description}" for s in senales
        ]
    else:
        lineas.append("  (ninguna)")
    if state.get("customer_snapshot") is not None:
        lineas.append(
            f"Perfil: promedio {state['customer_snapshot'].usual_amount_avg} "
            f"{state['customer_snapshot'].currency} · segmento "
            f"{state['customer_snapshot'].segment.value}"
        )
    else:
        lineas.append("Perfil: cliente sin perfil previo")
    return "\n".join(lineas)


@degrades(PRO_FRAUD)
async def debate_pro_fraud(state: GraphState, runtime: Runtime[GraphContext]) -> dict:
    """Construye el argumento acusatorio (ADR-0006)."""
    llm = runtime.context.llm
    if llm is None:
        return {"agent_route": [PRO_FRAUD], "pro_fraud_argument": ""}

    prompt = DEBATE_PRO_FRAUDE_PROMPT.format(evidencia=_formatear_evidencia(state))
    out = await llm.with_structured_output(DebateOut, method="json_mode").ainvoke(prompt)
    return {"agent_route": [PRO_FRAUD], "pro_fraud_argument": out.argument}


@degrades(PRO_CUSTOMER)
async def debate_pro_customer(state: GraphState, runtime: Runtime[GraphContext]) -> dict:
    """Construye el descargo del cliente (ADR-0006)."""
    llm = runtime.context.llm
    if llm is None:
        return {"agent_route": [PRO_CUSTOMER], "pro_customer_argument": ""}

    prompt = DEBATE_PRO_CLIENTE_PROMPT.format(evidencia=_formatear_evidencia(state))
    out = await llm.with_structured_output(DebateOut, method="json_mode").ainvoke(prompt)
    return {"agent_route": [PRO_CUSTOMER], "pro_customer_argument": out.argument}


# --- Nodos fatales: si fallan no hay caso, asi que lanzan ---


async def decision_arbiter(state: GraphState, runtime: Runtime[GraphContext]) -> dict:
    """Juicio bajo evidencia contradictoria (ADR-0006).

    Sin `citations_internal` no puede emitir veredicto autónomo: degrada a
    `ESCALATE_TO_HUMAN`. La ausencia de respaldo es la razón para llamar al
    humano (contrato §2.5). El ajuste de confianza es acotado (D4): el modelo
    propone la confianza final y el nodo la recorta al delta permitido sobre
    `base_confidence`, exigiendo justificación si se movió.
    """
    base = state.get("base_confidence")
    citas = state.get("citations_internal", [])
    if not citas or base is None:
        return {
            "agent_route": [ARBITER],
            "decision": DecisionType.ESCALATE_TO_HUMAN,
            "confidence": base or 0.0,
            "confidence_rationale": "sin respaldo interno recuperado: se escala a revisión humana",
        }

    llm = runtime.context.llm
    if llm is None:
        # Piso determinístico (ADR-0006): veredicto por precedencia sobre las
        # políticas detectadas por las señales (los sensores deterministas),
        # no sobre textos recuperados. Sin LLM no hay ajuste de confianza.
        codigos = {s.code for s in state.get("final_signals", state.get("signals", []))}
        return {
            "agent_route": [ARBITER],
            "decision": decision_desde_codigos(codigos, SIGNAL_TO_POLICY),
            "confidence": base,
            "confidence_rationale": (
                "veredicto determinístico por precedencia sobre señales (sin LLM)"
            ),
        }

    politicas = "\n".join(
        f"  - {c.policy_id} (v{c.version})" for c in citas
    )
    prompt = ARBITER_PROMPT.format(
        evidencia=_formatear_evidencia(state),
        pro_fraud=state.get("pro_fraud_argument", ""),
        pro_customer=state.get("pro_customer_argument", ""),
        politicas=politicas,
    )
    out = await llm.with_structured_output(ArbiterOut, method="json_mode").ainvoke(prompt)

    decision = out.decision
    if decision is DecisionType.ESCALATE_TO_HUMAN:
        confidence = base
    else:
        # Delta acotado: la confianza final no puede alejarse más de 0.2 de la
        # base. `confidence_rationale` se exige si hubo ajuste.
        confidence = min(1.0, max(0.0, out.confidence))
        delta = confidence - base
        if abs(delta) > 0.2:
            confidence = base + (0.2 if delta > 0 else -0.2)
        confidence = min(1.0, max(0.0, confidence))

    return {
        "agent_route": [ARBITER],
        "decision": decision,
        "confidence": confidence,
        "confidence_rationale": out.rationale,
    }


async def explainability(state: GraphState, runtime: Runtime[GraphContext]) -> dict:
    """Explicaciones en lenguaje natural para cliente y auditoría."""
    llm = runtime.context.llm
    if llm is None:
        return {
            "agent_route": [EXPLAIN],
            "explanation_customer": "",
            "explanation_audit": "",
        }

    politicas = "\n".join(
        f"  - {c.policy_id} (v{c.version})" for c in state.get("citations_internal", [])
    )
    prompt = EXPLAIN_PROMPT.format(
        decision=state.get("decision", "DESCONOCIDO"),
        confidence=state.get("confidence", 0.0),
        evidencia=_formatear_evidencia(state),
        politicas=politicas,
    )
    out = await llm.with_structured_output(ExplainOut, method="json_mode").ainvoke(prompt)
    return {
        "agent_route": [EXPLAIN],
        "explanation_customer": out.explanation_customer,
        "explanation_audit": out.explanation_audit,
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
                        for s in state.get("final_signals", state.get("signals", []))
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
