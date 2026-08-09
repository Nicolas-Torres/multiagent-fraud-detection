"""W0: la frontera de ingesta. `POST /cases` es idempotente por
`transaction_id` y el grafo corre en segundo plano, con su propia sesión —
la del request ya devolvió para cuando el grafo termina.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from multiagent_fraud_detection.api.deps import get_graph, get_graph_context, get_session
from multiagent_fraud_detection.db.models import Case, HumanResolution, Transaction
from multiagent_fraud_detection.enums import CaseStatus
from multiagent_fraud_detection.graph.context import GraphContext
from multiagent_fraud_detection.schemas.case import CaseCreated, CaseDetail, CaseSummary
from multiagent_fraud_detection.schemas.human_resolution import HumanResolutionIn
from multiagent_fraud_detection.schemas.pagination import Page
from multiagent_fraud_detection.schemas.transaction import TransactionIn

logger = logging.getLogger(__name__)

router = APIRouter(tags=["cases"])


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
    """
    await _marcar(contexto, case_id, CaseStatus.ANALYZING)
    try:
        await graph.ainvoke(
            {"case_id": case_id, "transaction": transaction}, context=contexto
        )
    except Exception:  # noqa: BLE001 - es exactamente lo que W1 existe para atrapar
        logger.exception("caso %s no llegó a un veredicto", case_id)
        await _marcar(contexto, case_id, CaseStatus.FAILED)


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
