"""Nodos del grafo.

Stubs: cada uno escribe una constante en su clave y registra su paso. Se
reemplazan de a uno; la firma y el contrato de retorno ya son los definitivos.

Un nodo devuelve SOLO las claves que escribe. Para las claves con reducer
(zona 2 del estado) devuelve solo su aporte, nunca la lista acumulada.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from functools import wraps

from langgraph.runtime import Runtime
from sqlalchemy import delete, update

from multiagent_fraud_detection.db.models import AgentError as AgentErrorRow
from multiagent_fraud_detection.db.models import Case, Decision, Signal
from multiagent_fraud_detection.db.repositories.customer_behavior import profile_for
from multiagent_fraud_detection.db.repositories.policy_chunks import search_similar
from multiagent_fraud_detection.db.repositories.transaction_history import (
    history_for_customer,
    history_for_device,
)
from multiagent_fraud_detection.enums import CaseStatus, DecisionType, Severity
from multiagent_fraud_detection.domain.catalog import Owner
from multiagent_fraud_detection.domain.engine import evaluate, prescribed_action
from multiagent_fraud_detection.domain.predicates import EvalContext
from multiagent_fraud_detection.domain.scoring import (
    SCORING_VERSION,
    base_confidence,
    has_contradiction,
    risk_score,
    signal_sort_key,
)
from multiagent_fraud_detection.graph.context import GraphContext
from multiagent_fraud_detection.graph.state import (
    AgentError,
    GraphState,
    RetrievedChunk,
    WorkingSignal,
)
from multiagent_fraud_detection.retrieval.citations import (
    authorization_citations,
    merge_citations,
    missing_authorization,
)
from multiagent_fraud_detection.retrieval.embeddings import format_query
from multiagent_fraud_detection.retrieval.query import build_query, query_codes

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

# Cuantos fragmentos trae la pierna de descubrimiento. Con once documentos, cinco
# es casi la mitad del corpus: lo que recupere de mas lo filtra el Arbiter, y lo
# que recupere de menos no lo recupera nadie. El numero se revisa cuando el
# corpus deje de ser once lineas, y el paso de ablacion es el que lo va a decir.
RAG_TOP_K = 5

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
        async def wrapper(*args, **kwargs) -> dict:
            # `*args` y no `(state)`: los nodos que necesitan `GraphContext`
            # reciben tambien `runtime`. `@wraps` preserva `__wrapped__`, asi
            # que LangGraph inspecciona la firma ORIGINAL para decidir que
            # pasar; el wrapper solo tiene que reenviarlo.
            try:
                return await fn(*args, **kwargs)
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


def _a_working(señales, emitido_por: str) -> list[WorkingSignal]:
    """`EmittedSignal` del dominio -> `WorkingSignal` del estado.

    El dominio no conoce el grafo: sus senales no traen `emitted_by`. La
    procedencia la pone el nodo, que es quien la sabe. `observed` no viaja al
    estado —es evidencia numerica para el Arbiter y el monitoreo, no parte de
    `Signal`— pero se conserva en `description`, que si se persiste.
    """
    return [
        WorkingSignal(
            code=s.code,
            description=s.description,
            severity=s.severity,
            emitted_by=emitido_por,
        )
        for s in señales
    ]


# --- Ola 1: independientes entre si ---


@degrades(CONTEXT)
async def transaction_context(
    state: GraphState, runtime: Runtime[GraphContext]
) -> dict:
    """Senales que no requieren conocer al cliente.

    Es el **piso de evidencia** del sistema: el unico agente que sigue
    produciendo senales cuando el cliente no tiene perfil —el escenario que el
    contrato llama "el que mas importa"—. Por eso no consulta el perfil ni el
    historial: si lo hiciera, dejaria de funcionar justo cuando hace falta.

    Que evalue una sola politica (FP-07) no es un defecto del reparto: es lo que
    resulta de derivarlo de los insumos que declara cada predicado (ADR-0007).
    """
    ctx = EvalContext(
        transaction=state["transaction"],
        blacklist=await runtime.context.blacklist.get(runtime.context.session_factory),
    )
    resultado = evaluate(runtime.context.catalog, Owner.CONTEXT, ctx)

    return {
        "agent_route": [CONTEXT],
        "signals": _a_working(resultado.signals, CONTEXT),
        "matched_policies": list(resultado.matched_policies),
    }


@degrades(BEHAVIORAL)
async def behavioral_pattern(
    state: GraphState, runtime: Runtime[GraphContext]
) -> dict:
    """Contraste contra el perfil y el historial del cliente.

    Nueve de las diez politicas evaluables. Tres consultas —perfil, historial de
    la cuenta, historial del dispositivo— y despues aritmetica pura: la logica
    esta toda en `domain/`, probada sobre las 7 000 transacciones sin base.

    **El `as_of` es el timestamp de la transaccion, jamas `now()`.** Es el punto
    mas delicado de la etapa: `now()` funciona perfecto en produccion —el futuro
    no esta en la tabla cuando llega el caso— y solo miente en evaluacion, donde
    el dataset se carga completo. Fallaria hacia arriba, viendo rafagas enteras
    desde su primera transaccion e inflando su propio recall. El repositorio hace
    cumplir el filtro; aca solo hay que pasarle el valor correcto.
    """
    transaccion = state["transaction"]
    as_of = transaccion.timestamp

    async with runtime.context.session_factory() as session:
        # Secuencial y en una sola sesion, no `asyncio.gather`: una `AsyncSession`
        # no admite operaciones concurrentes. Las tres consultas usan indice y
        # cuestan menos que abrir dos sesiones mas.
        perfil = await profile_for(session, customer_id=transaccion.customer_id)
        hist_cliente = await history_for_customer(
            session,
            customer_id=transaccion.customer_id,
            as_of=as_of,
            exclude_transaction_id=transaccion.transaction_id,
        )
        hist_dispositivo = await history_for_device(
            session,
            device_id=transaccion.device_id,
            as_of=as_of,
            exclude_transaction_id=transaccion.transaction_id,
        )

    ctx = EvalContext(
        transaction=transaccion,
        profile=perfil,
        history_customer=tuple(hist_cliente),
        history_device=tuple(hist_dispositivo),
    )
    resultado = evaluate(runtime.context.catalog, Owner.BEHAVIORAL, ctx)
    señales = _a_working(resultado.signals, BEHAVIORAL)

    if perfil is None:
        # La unica senal que no sale de un predicado. No es una observacion
        # sobre la transaccion sino sobre la **evidencia**: el agente declara
        # que no pudo comparar. `customer_snapshot=None` no lo comunica —seria
        # indistinguible de "el nodo no corrio"—; la senal si.
        señales.insert(
            0,
            WorkingSignal(
                code="NO_CUSTOMER_PROFILE",
                description=(
                    f"El cliente {transaccion.customer_id} no tiene perfil de "
                    f"comportamiento: {len(resultado.skipped_policies)} politicas "
                    f"no son evaluables"
                ),
                severity=Severity.MEDIUM,
                emitted_by=BEHAVIORAL,
            ),
        )

    return {
        "agent_route": [BEHAVIORAL],
        "customer_snapshot": perfil,
        "signals": señales,
        "matched_policies": list(resultado.matched_policies),
    }


@degrades(THREAT_INTEL)
async def external_threat_intel(state: GraphState) -> dict:
    return {"agent_route": [THREAT_INTEL], "citations_external": [], "discarded_sources": []}


# --- Ola 2 ---


async def _descubrir(
    state: GraphState, runtime: Runtime[GraphContext]
) -> list[RetrievedChunk]:
    """La pierna de descubrimiento: politicas relacionadas que NO dispararon.

    Sin garantia por definicion: es recuperacion aproximada. Su valor es lo que
    la autorizacion no puede dar —contexto para el Arbiter, y la unica via por la
    que una politica no evaluable llega a un caso—.
    """
    codigos = query_codes(s.code for s in state.get("signals", []))
    if not codigos:
        # Sin senales no hay nada que preguntar. Una query vacia recuperaria los
        # k documentos mas cercanos al vector de la cadena vacia, que es ruido
        # con forma de evidencia.
        return []

    ctx = runtime.context
    vector = ctx.query_cache.get(codigos)

    if vector is None:
        texto = format_query(build_query(codigos, ctx.vocabulary))
        # `to_thread` porque el cliente del proveedor es sincrono: llamarlo
        # directo bloquearia el event loop durante toda la latencia de red, y
        # con el las ramas hermanas del superstep.
        vector = await asyncio.to_thread(ctx.embedder.embed, texto)
        ctx.query_cache.put(codigos, vector)

    async with ctx.session_factory() as session:
        matches = await search_similar(session, vector, limit=RAG_TOP_K)

    return [
        RetrievedChunk(
            policy_id=m.policy_id,
            chunk_id=m.chunk_id,
            version=m.source_version,
            content=m.content,
            score=m.score,
        )
        for m in matches
    ]


@degrades(POLICY_RAG)
async def internal_policy_rag(
    state: GraphState, runtime: Runtime[GraphContext]
) -> dict:
    """Las dos piernas de ADR-0011. Lo que se persiste es su union.

    **`@degrades` solo no alcanza, y es lo mas importante de este nodo.** Si el
    proveedor de embeddings se cae y la excepcion llega al decorador, el nodo
    devuelve cero citas: se pierde tambien la autorizacion y todo caso escala.
    Exactamente lo contrario de lo que el ADR promete. Por eso el descubrimiento
    lleva su **propio** `try` y registra el error a mano, mientras la
    autorizacion sigue su camino. El decorador queda como red para lo imprevisto.

    La autorizacion no consulta el indice ni la red: sale del catalogo. Ver
    `retrieval/citations.py`.
    """
    politicas = sorted(set(state.get("matched_policies", [])))
    autorizadas = authorization_citations(runtime.context.catalog, politicas)

    chunks: list[RetrievedChunk] = []
    errores: list[AgentError] = []

    try:
        chunks = await _descubrir(state, runtime)
    except Exception as exc:  # noqa: BLE001 - degradar la pierna, no el nodo
        logger.exception("descubrimiento degradado; la autorizacion sobrevive")
        errores.append(
            AgentError(
                agent=POLICY_RAG,
                error_type=type(exc).__name__,
                message=f"descubrimiento no disponible: {exc}",
            )
        )

    citas = merge_citations(autorizadas, chunks)

    # Invariante estructural de ADR-0011, afirmado donde se produce. No es una
    # metrica: si esto falla, el codigo de arriba tiene un bug, no el catalogo.
    faltantes = missing_authorization(citas, politicas)
    assert not faltantes, f"politicas sin cita de autorizacion: {faltantes}"

    return {
        "agent_route": [POLICY_RAG],
        "citations_internal": citas,
        "rag_chunks": chunks,
        "agent_errors": errores,
    }


@degrades(AGGREGATE)
async def evidence_aggregation(
    state: GraphState, runtime: Runtime[GraphContext]
) -> dict:
    """Consolida la evidencia de la ola 1 y produce los scores determinísticos.

    No tiene logica de deteccion: no evalua politicas ni mira la transaccion.
    Recibe lo que produjeron los agentes y lo deja en una forma unica —sin
    duplicados, ordenada, medida— para que el Arbiter reciba lo mismo en cada
    corrida.

    **Sin `@degrades` a proposito.** Los nodos de la ola 1 degradan porque su
    falla deja evidencia incompleta y el caso puede seguir. Si este fallara no
    habria nada que consolidar: es el unico camino hacia la decision, y una
    degradacion silenciosa produciria un caso sin scores que el invariante
    rechazaria mas adelante, lejos de la causa.
    """
    señales = state.get("signals", [])
    politicas = state.get("matched_policies", [])
    errores = state.get("agent_errors", [])
    catalogo = runtime.context.catalog

    # 1. Deduplicar por codigo. Los dos agentes pueden emitir el mismo: hoy no
    #    ocurre —ninguna politica cruza los nodos— pero eso depende del catalogo,
    #    que es dato mutable. Gana la primera aparicion.
    unicas: dict[str, WorkingSignal] = {}
    for señal in señales:
        unicas.setdefault(señal.code, señal)

    # 2. Orden deterministico: severidad descendente, luego codigo.
    ordenadas = sorted(
        unicas.values(), key=lambda s: signal_sort_key(s.code, s.severity)
    )

    # 3. Politicas sin duplicar y en orden estable.
    unicas_politicas = sorted(set(politicas))

    # 4. Los dos scores.
    #
    # `NO_CUSTOMER_PROFILE` **no entra en el riesgo**. Es la unica senal que no
    # sale de un predicado: no describe la transaccion, describe que faltó con
    # que compararla. Sumarla al riesgo seria el mismo error de categoria que
    # sumar un agente caido —"no pude evaluar" no es "esto es sospechoso"— y
    # ademas subiria el riesgo de las ~96 transacciones sin perfil por una razon
    # que no es de ellas.
    #
    # Donde si pesa es en la confianza, y una sola vez: por la penalizacion.
    sin_perfil = any(s.code == "NO_CUSTOMER_PROFILE" for s in ordenadas)
    riesgo = risk_score(
        s.severity for s in ordenadas if s.code != "NO_CUSTOMER_PROFILE"
    )
    degradados = sorted({e.agent for e in errores})
    confianza = base_confidence(
        riesgo,
        degraded_agents=degradados,
        contradiction=has_contradiction(
            catalogo[pid].action for pid in unicas_politicas
        ),
        missing_profile=sin_perfil,
    )

    return {
        "agent_route": [AGGREGATE],
        "evidence": ordenadas,
        "policies": unicas_politicas,
        "risk_score": riesgo,
        "base_confidence": confianza,
        "scoring_version": SCORING_VERSION,
    }


@degrades(PRO_FRAUD)
async def debate_pro_fraud(state: GraphState) -> dict:
    return {"agent_route": [PRO_FRAUD], "pro_fraud_argument": "stub"}


@degrades(PRO_CUSTOMER)
async def debate_pro_customer(state: GraphState) -> dict:
    return {"agent_route": [PRO_CUSTOMER], "pro_customer_argument": "stub"}


# --- Nodos fatales: si fallan no hay caso, asi que lanzan ---


async def decision_arbiter(
    state: GraphState, runtime: Runtime[GraphContext]
) -> dict:
    """Linea base deterministica: el veredicto que el catalogo prescribe.

    **No es el Arbiter final.** Es el brazo de control que ADR-0006 prometio para
    la comparacion del entregable 7: el mismo calculo con el que se construyo
    `expected_decision`, de modo que el enfoque agentico se mida contra algo y no
    contra nada. El Arbiter con LLM lo reemplaza y puede apartarse con
    justificacion auditable.

    No ajusta la confianza: `confidence == base_confidence` y no hay
    `confidence_rationale`. Un ajuste sin justificacion es justo lo que la tercera
    guarda de W2 prohibe, y este arbitro no tiene con que justificar.

    ## Las dos degradaciones

    Degrada a `ESCALATE_TO_HUMAN` **antes** de que las guardas puedan dispararse.
    Que una guarda levante significa `FAILED`, y la ausencia de respaldo no es un
    error del sistema: es la razon por la que existe la cola humana.
    """
    politicas = state.get("policies", sorted(set(state.get("matched_policies", []))))
    citas = state.get("citations_internal", [])
    base = state.get("base_confidence")

    faltantes = missing_authorization(citas, politicas)
    if faltantes:
        # No deberia ocurrir: la autorizacion no consulta el indice ni la red. Si
        # ocurre, el nodo del RAG fallo entero y su red exterior lo trago. Emitir
        # un veredicto aqui seria bloquear sin poder decir bajo que norma.
        return {
            "agent_route": [ARBITER],
            "decision": DecisionType.ESCALATE_TO_HUMAN,
            "confidence": base if base is not None else 0.0,
            "confidence_rationale": (
                f"sin respaldo interno para {', '.join(faltantes)}: "
                f"la evidencia esta incompleta"
            ),
        }

    if base is None:
        return {
            "agent_route": [ARBITER],
            "decision": DecisionType.ESCALATE_TO_HUMAN,
            "confidence": 0.0,
            "confidence_rationale": "sin score deterministico: no hubo consolidacion",
        }

    return {
        "agent_route": [ARBITER],
        "decision": prescribed_action(runtime.context.catalog, tuple(politicas)),
        "confidence": base,
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

        # **Contencion, no "lista no vacia".** La formulacion anterior era falsa
        # por dos lados. Debil: una lista con las citas equivocadas la satisface,
        # y el sistema puede bloquear citando normas que no aplico. E imposible:
        # ninguna vinculacion puede prescribir APPROVE —el catalogo lo rechaza al
        # cargar—, asi que ninguna cita puede respaldar una aprobacion y el 90%
        # del trafico, que no dispara nada, no tendria salida.
        #
        # La obligacion nace de la evidencia: si una politica disparo, tiene que
        # estar citada. Si no disparo ninguna, no hay nada que exigir.
        faltantes = missing_authorization(
            state.get("citations_internal", []), state.get("policies", [])
        )
        if faltantes:
            raise ValueError(
                f"veredicto autonomo sin respaldo para {', '.join(faltantes)}"
            )
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
                    matched_policies=state.get("policies", []),
                    policy_catalog_version=runtime.context.catalog.version,
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
                        for s in state.get("evidence", state.get("signals", []))
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
