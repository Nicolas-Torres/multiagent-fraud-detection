"""Memoria de trabajo del grafo de agentes.

Frontera interna: no la ve el dashboard. La proyeccion a las tablas ocurre en
un unico nodo persistidor al final del grafo.

Zonas: (1) entrada inmutable, la escribe el borde HTTP; (2) evidencia
acumulada, varios escritores; (3) producciones unicas, un escritor;
(4) scratch interno, no se persiste. Las zonas 2-4 se leen con `.get()`.

Sin `from __future__ import annotations`: LangGraph resuelve las anotaciones
en runtime para descubrir los reducers.
"""

import operator
from datetime import UTC, datetime
from typing import Annotated, TypedDict
from uuid import UUID

from pydantic import BaseModel, Field

from multiagent_fraud_detection.enums import DecisionType
from multiagent_fraud_detection.schemas.customer_behavior import CustomerBehaviorRead
from multiagent_fraud_detection.schemas.decision import (
    ExternalCitation,
    InternalCitation,
    SignalRead,
)
from multiagent_fraud_detection.schemas.transaction import TransactionIn

# --- Tipos internos: no cruzan a `schemas/`, que es la frontera publica ---


class WorkingSignal(SignalRead):
    """Senal en vuelo. `emitted_by` la consumen Evidence Aggregation (para
    fusionar redundantes) y el harness (para atribuir falsos positivos);
    se descarta al persistir, porque `Signal` no expone procedencia."""

    emitted_by: str


class AgentError(BaseModel):
    """Falla parcial. Degrada la decision, no aborta el grafo: `FAILED` es
    solo para una excepcion no capturada, y la escribe el background task."""

    agent: str
    error_type: str
    message: str
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RetrievedChunk(InternalCitation):
    """Chunk crudo del RAG: la cita interna es este objeto menos el payload."""

    content: str
    score: float


class DiscardedSource(BaseModel):
    url: str  # `str` y no `HttpUrl`: una fuente rechazada puede venir malformada
    reason: str


# --- El estado ---


class GraphInput(TypedDict):
    """Se usa como `input_schema=` al compilar: fija que el grafo solo recibe esto."""

    case_id: UUID
    transaction: TransactionIn


class GraphState(GraphInput, total=False):
    """Las dos claves de `GraphInput` son las unicas requeridas; el resto se
    llena progresivamente y su ausencia significa "todavia no"."""

    # Zona 2 - con reducer, cada nodo devuelve SOLO su aporte; devolver la
    # lista acumulada duplica en silencio.
    signals: Annotated[list[WorkingSignal], operator.add]
    agent_route: Annotated[list[str], operator.add]
    agent_errors: Annotated[list[AgentError], operator.add]
    # Las politicas que dispararon completas. Las escriben Context y Behavioral
    # —cada uno las suyas, ninguna cruza los dos nodos (ADR-0007)—, asi que es
    # multi-escritor y lleva reducer. Es el vocabulario en el que habla el
    # ground truth: sin esta clave el harness compara senales atomicas contra
    # `expected_policies` y no hay comparacion posible.
    matched_policies: Annotated[list[str], operator.add]

    # Zona 3 - un escritor por clave (los nodos de debate corren en paralelo
    # pero escriben claves distintas, por eso no necesitan reducer).
    customer_snapshot: CustomerBehaviorRead | None  # None = el nodo no corrio;
    # "cliente sin perfil" es la senal NO_CUSTOMER_PROFILE
    # `signals` y `matched_policies` (zona 2) son **acumuladores**: cada agente
    # suma lo suyo y nadie puede reemplazar el total, porque su reducer es
    # aditivo. Evidence Aggregation produce la version consolidada —sin
    # duplicados y ordenada— y la deja aca, con semantica de ultima escritura.
    #
    # Que sean claves distintas no es un rodeo: son cosas distintas. Una es lo
    # que cada agente vio; la otra, lo que el caso archiva. El persistidor lee
    # esta; el debate y el Arbiter tambien.
    evidence: list[WorkingSignal]
    policies: list[str]
    citations_internal: list[InternalCitation]
    citations_external: list[ExternalCitation]
    pro_fraud_argument: str
    pro_customer_argument: str
    # `float` y no el alias `Confidence`: en un TypedDict nada valida, y el
    # rango se hace cumplir donde el valor se produce.
    risk_score: float
    base_confidence: float
    scoring_version: str
    decision: DecisionType
    confidence: float
    confidence_rationale: str
    explanation_customer: str
    explanation_audit: str

    # Zona 4
    rag_chunks: list[RetrievedChunk]
    discarded_sources: list[DiscardedSource]
