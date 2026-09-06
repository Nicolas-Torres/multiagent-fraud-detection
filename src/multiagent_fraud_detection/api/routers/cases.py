"""W0: la frontera de ingesta. `POST /cases` es idempotente por
`transaction_id` y el grafo corre en segundo plano, con su propia sesión —
la del request ya devolvió para cuando el grafo termina.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    Response,
    status,
)
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from multiagent_fraud_detection.api import case_progress
from multiagent_fraud_detection.api.deps import (
    get_graph,
    get_graph_context,
    get_session,
)
from multiagent_fraud_detection.db.models import Case, HumanResolution, Transaction
from multiagent_fraud_detection.enums import CaseStatus
from multiagent_fraud_detection.graph.context import GraphContext
from multiagent_fraud_detection.schemas.case import CaseCreated, CaseDetail, CaseSummary
from multiagent_fraud_detection.schemas.human_resolution import HumanResolutionIn
from multiagent_fraud_detection.schemas.pagination import Page
from multiagent_fraud_detection.schemas.transaction import TransactionIn

logger = logging.getLogger(__name__)

router = APIRouter(tags=["cases"])

# Cooldown de la demo pública del dashboard (portafolio, sin autenticación):
# protege el costo de LLM de un visitante que clickea "ejecutar" repetido,
# no es dato de negocio ni parte del contrato documentado de `POST /cases`
# — por eso vive en memoria del proceso, y por eso sólo mira
# `transaction_id` con el prefijo `LIVE-` que arma el frontend para los
# escenarios ejecutables. Cualquier otro llamador de este endpoint (el
# real, el que describe el contrato) nunca pasa por acá.
#
# Global por escenario, no por IP: sin sesiones ni autenticación no hay con
# qué identificar visitantes, y global es más simple y ya cubre el riesgo
# real (gasto de API, no abuso dirigido a una persona).
LIVE_PREFIX = "LIVE-"
LIVE_COOLDOWN = timedelta(minutes=1)
_ultima_corrida_por_escenario: dict[str, datetime] = {}


def _escenario_de(transaction_id: str) -> str | None:
    if not transaction_id.startswith(LIVE_PREFIX):
        return None
    return transaction_id.removeprefix(LIVE_PREFIX).split("-", 1)[0]


def _cooldown_restante(transaction_id: str) -> timedelta | None:
    escenario = _escenario_de(transaction_id)
    if escenario is None:
        return None
    ultima = _ultima_corrida_por_escenario.get(escenario)
    if ultima is None:
        return None
    restante = LIVE_COOLDOWN - (datetime.now(UTC) - ultima)
    return restante if restante > timedelta(0) else None


def _marcar_corrida(transaction_id: str) -> None:
    escenario = _escenario_de(transaction_id)
    if escenario is not None:
        _ultima_corrida_por_escenario[escenario] = datetime.now(UTC)


async def _marcar(contexto: GraphContext, case_id: UUID, status_: CaseStatus) -> None:
    async with contexto.session_factory() as session:
        async with session.begin():
            await session.execute(
                update(Case).where(Case.case_id == case_id).values(status=status_)
            )


async def _correr_grafo(
    graph: Any, contexto: GraphContext, case_id: UUID, transaction: TransactionIn
) -> None:
    """W1: el wrapper del background task (§7.3 del contrato).

    Escribe `ANALYZING` **antes** de invocar el grafo -distingue "aceptado"
    (W0, `RECEIVED`) de "corriendo"- y es el único lugar que escribe
    `FAILED`: ningún nodo lo hace, porque un agente caído degrada, no
    aborta (`@degrades`). `FAILED` es exclusivamente para una excepción que
    escapó del grafo entero, la que este `try` atrapa.

    `astream(stream_mode="updates")` en vez de `ainvoke()` (ADR-0018): cada
    paso entrega un dict de una sola clave -el nombre del nodo que acaba de
    terminar-, incluso para nodos que corrieron en el mismo superstep
    paralelo. Publicarlo es puramente un efecto secundario para la demo en
    vivo del dashboard; el resultado que W2 persiste no cambia en nada.
    """
    await _marcar(contexto, case_id, CaseStatus.ANALYZING)
    try:
        async for actualizacion in graph.astream(
            {"case_id": case_id, "transaction": transaction},
            context=contexto,
            stream_mode="updates",
        ):
            for nodo in actualizacion:
                case_progress.publicar(case_id, nodo)
    except Exception:
        logger.exception("caso %s no llegó a un veredicto", case_id)
        await _marcar(contexto, case_id, CaseStatus.FAILED)
    finally:
        case_progress.cerrar(case_id)


async def _caso_existente(session: AsyncSession, transaction_id: str) -> Case | None:
    return await session.scalar(
        select(Case).where(Case.transaction_id == transaction_id)
    )


@router.post(
    "/cases",
    response_model=CaseCreated,
    status_code=status.HTTP_202_ACCEPTED,
)
async def crear_caso(
    transaction: TransactionIn,
    background_tasks: BackgroundTasks,
    response: Response,
    session: AsyncSession = Depends(get_session),
    graph: Any = Depends(get_graph),
    contexto: GraphContext = Depends(get_graph_context),
) -> CaseCreated:
    """`transaction_id` es la clave de idempotencia (§2.4 del contrato):
    existente → `200` con el `case_id` existente, sin volver a correr el
    grafo; nuevo → `202`, arranca en segundo plano.

    El `IntegrityError` en el `except` no es paranoia: dos requests con el
    mismo `transaction_id` casi en simultáneo pueden pasar los dos el
    `SELECT` antes de que cualquiera commitee — la unicidad la garantiza la
    base (`cases_transaction_id_key`), no este chequeo, que sólo evita la
    vuelta al grafo en el caso común.
    """
    restante = _cooldown_restante(transaction.transaction_id)
    if restante is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                "este escenario de demo se corrió hace poco, "
                f"reintentá en {int(restante.total_seconds())}s"
            ),
        )

    existente = await _caso_existente(session, transaction.transaction_id)
    if existente is not None:
        response.status_code = status.HTTP_200_OK
        return CaseCreated.model_validate(existente)

    caso = Case(transaction_id=transaction.transaction_id, status=CaseStatus.RECEIVED)
    try:
        # Sin `session.begin()` explícito: el `SELECT` de arriba ya abrió
        # una transacción por autobegin (SQLAlchemy 2.0), y `.begin()` sobre
        # una sesión que ya tiene una en curso levanta `InvalidRequestError`.
        session.add(Transaction(**transaction.model_dump()))
        session.add(caso)
        await session.commit()
    except IntegrityError:
        await session.rollback()
        existente = await _caso_existente(session, transaction.transaction_id)
        if existente is None:
            raise
        response.status_code = status.HTTP_200_OK
        return CaseCreated.model_validate(existente)

    await session.refresh(caso)

    _marcar_corrida(transaction.transaction_id)
    background_tasks.add_task(
        _correr_grafo, graph, contexto, caso.case_id, transaction
    )

    return CaseCreated.model_validate(caso)


@router.get("/cases", response_model=Page[CaseSummary])
async def listar_casos(
    status: CaseStatus | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> Page[CaseSummary]:
    """La cola HITL (§3 del contrato): `GET /cases?status=PENDING_HUMAN` es
    la vista que el dashboard filtra. El índice `ix_cases_status_created_at`
    ya está pensado para este `WHERE status = ... ORDER BY created_at`.
    """
    filtro = select(Case)
    if status is not None:
        filtro = filtro.where(Case.status == status)

    total = await session.scalar(
        select(func.count()).select_from(filtro.subquery())
    )
    pagina = filtro.order_by(Case.created_at.desc()).limit(limit).offset(offset)
    casos = (await session.scalars(pagina)).all()

    return Page(
        items=[CaseSummary.from_case(c) for c in casos],
        total=total or 0,
        limit=limit,
        offset=offset,
    )


@router.get("/cases/{case_id}", response_model=CaseDetail)
async def detalle_caso(
    case_id: UUID, session: AsyncSession = Depends(get_session)
) -> CaseDetail:
    caso = await session.get(Case, case_id)
    if caso is None:
        raise HTTPException(status_code=404, detail="caso no encontrado")
    return CaseDetail.model_validate(caso)


_ESTADOS_EN_CURSO = frozenset({CaseStatus.RECEIVED, CaseStatus.ANALYZING})


async def _eventos_de_progreso(
    case_id: UUID, contexto: GraphContext
) -> AsyncIterator[str]:
    """Cuerpo `text/event-stream` de `GET /cases/{case_id}/stream` (ADR-0018).

    Se suscribe **antes** de mirar el estado en base -no al revés-: si se
    mirara primero, un caso podría pasar de `ANALYZING` a terminal en la
    ventana entre esa lectura y la suscripción, y el evento `done` que
    `_correr_grafo` publica en su `finally` se perdería para siempre. Con la
    suscripción primero, ese evento -si llega a tiempo- se encola igual.

    El primer superstep del grafo (reglas deterministas) suele terminar
    antes de que el navegador cierre el handshake del `EventSource` -por
    eso `suscribirse` también entrega el historial acumulado hasta ese
    instante, y acá se reproduce antes de pasar a esperar eventos nuevos.
    """
    cola, historial = case_progress.suscribirse(case_id)
    try:
        async with contexto.session_factory() as session:
            caso = await session.get(Case, case_id)

        if caso is None or caso.status not in _ESTADOS_EN_CURSO:
            yield "event: done\ndata: {}\n\n"
            return

        for nodo in historial:
            yield f"event: node\ndata: {json.dumps({'node': nodo})}\n\n"

        while True:
            item = await cola.get()
            if item is case_progress.FIN:
                yield "event: done\ndata: {}\n\n"
                return
            yield f"event: node\ndata: {json.dumps({'node': item})}\n\n"
    finally:
        case_progress.desuscribirse(case_id, cola)


@router.get("/cases/{case_id}/stream")
async def progreso_caso(
    case_id: UUID, contexto: GraphContext = Depends(get_graph_context)
) -> StreamingResponse:
    """No es fuente de verdad (§7.3 del contrato) — `GET /cases/{case_id}`
    sigue siendo la única forma confiable de conocer el veredicto; esto es
    puramente un agregado visual para la demo en vivo del dashboard.
    """
    return StreamingResponse(
        _eventos_de_progreso(case_id, contexto), media_type="text/event-stream"
    )


@router.post("/cases/{case_id}/resolution", response_model=CaseDetail)
async def resolver_caso(
    case_id: UUID,
    resolucion: HumanResolutionIn,
    session: AsyncSession = Depends(get_session),
) -> CaseDetail:
    """W3 (§7.3 del contrato): el grafo ya terminó -`PENDING_HUMAN` es
    terminal, no hay `interrupt()` que reanudar (ADR de la etapa del grafo)-,
    así que resolver es sólo escribir `human_resolutions` y pasar el caso a
    `RESOLVED`. Sólo válido sobre un caso que de verdad está esperando: otro
    estado es `409`, no una resolución que reescriba lo que W2 ya decidió.
    """
    caso = await session.get(Case, case_id)
    if caso is None:
        raise HTTPException(status_code=404, detail="caso no encontrado")
    if caso.status is not CaseStatus.PENDING_HUMAN:
        raise HTTPException(
            status_code=409,
            detail=f"el caso está en {caso.status.value}, no en PENDING_HUMAN",
        )

    session.add(HumanResolution(case_id=case_id, **resolucion.model_dump()))
    caso.status = CaseStatus.RESOLVED
    await session.commit()
    await session.refresh(caso)

    return CaseDetail.model_validate(caso)
