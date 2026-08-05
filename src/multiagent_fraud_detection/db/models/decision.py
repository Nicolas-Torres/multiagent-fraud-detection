from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import DateTime, Enum as SQLEnum, Float, ForeignKey, String, Text, func

from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from multiagent_fraud_detection.db.base import Base
from multiagent_fraud_detection.enums import DecisionType

if TYPE_CHECKING:
    from multiagent_fraud_detection.db.models.case import Case
    from multiagent_fraud_detection.db.models.signal import Signal
    from multiagent_fraud_detection.db.models.agent_error import AgentError


class Decision(Base):
    __tablename__ = "decisions"

    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("cases.case_id", ondelete="CASCADE"),
        primary_key=True
    )

    decision: Mapped[DecisionType] = mapped_column(
        SQLEnum(DecisionType, native_enum=False)
    )

    confidence: Mapped[float] = mapped_column(Float)

    risk_score: Mapped[float | None] = mapped_column(Float)

    base_confidence: Mapped[float | None] = mapped_column(Float)

    confidence_rationale: Mapped[str | None] = mapped_column(Text)

    scoring_version: Mapped[str | None] = mapped_column(String(16))

    # Las politicas que dispararon completas. `ARRAY` y no tabla por la regla de
    # §7.2: escalares homogeneos, se leen siempre completos, no existen sin su
    # dueno. Mismo caso que `agent_route`.
    #
    # Es el vocabulario en el que habla el ground truth (`expected_policies`).
    # Sin esta columna el harness compara senales atomicas contra politicas, y
    # esa correspondencia no es reconstruible: una politica es la conjuncion de
    # dos o tres senales.
    matched_policies: Mapped[list[str] | None] = mapped_column(ARRAY(String))

    # Que version del catalogo se evaluo. Con las politicas como dato mutable
    # (ADR-0007), una decision de enero auditada contra el catalogo de marzo no
    # es auditable. `scoring_version` sella la formula; esto sella la norma.
    policy_catalog_version: Mapped[str | None] = mapped_column(String(32))

    # Como se derivo el vector con el que se recupero: modelo, dimension,
    # task_type y generacion (`gemini-embedding-2:1536:doc:1`). ADR-0012.
    #
    # Con los otros dos sellos cierra la auditoria en tres ejes independientes:
    # `InternalCitation.version` dice que texto se cito,
    # `policy_catalog_version` que traduccion se evaluo, y esto como se derivo
    # el vector. Los tres son necesarios porque los tres artefactos cambian por
    # separado y ninguno registra los cambios de los otros.
    #
    # Cadena descriptiva y no id opaco: el motivo de sellarla es que alguien la
    # lea dos anos despues. Por lo mismo el modelo no es variable de entorno —un
    # modelo cambiable sin que suba esta version haria mentir a los tres sellos
    # a la vez—.
    #
    # Nullable por expand/contract y porque las decisiones ya persistidas no
    # tuvieron indice.
    retrieval_index_version: Mapped[str | None] = mapped_column(String(64))

    # Con que prompt y modelo se redacto `explanation_customer`. Cuarto sello,
    # y el unico que cubre texto generado: editar el prompt sin subir la
    # generacion produce mensajes distintos bajo la misma version, y ninguna
    # consulta lo detecta.
    #
    # `null` cuando la explicacion salio de la plantilla de respaldo —proveedor
    # caido o sin clave—. No es dato faltante: dice que ningun modelo participo.
    explanation_prompt_version: Mapped[str | None] = mapped_column(String(64))

    citations_internal: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)

    citations_external: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)

    debate_pro_fraud: Mapped[str] = mapped_column(Text)

    debate_pro_customer: Mapped[str] = mapped_column(Text)

    agent_route: Mapped[list[str]] = mapped_column(ARRAY(String))

    explanation_customer: Mapped[str] = mapped_column(Text)

    explanation_audit: Mapped[str] = mapped_column(Text)

    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now()
    )

    case: Mapped["Case"] = relationship(back_populates="decision")

    signals: Mapped[list["Signal"]] = relationship(
        back_populates="decision",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="Signal.id",
    )

    @property
    def debate(self) -> dict[str, str]:
        """Recompone el objeto valor que el contrato expone como `debate`."""
        return {
            "pro_fraud_argument": self.debate_pro_fraud,
            "pro_customer_argument": self.debate_pro_customer,
        }

    agent_errors: Mapped[list["AgentError"]] = relationship(
        back_populates="decision",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="AgentError.id",
    )

    @property
    def degraded_agents(self) -> list[str]:
        """Agentes que fallaron durante el analisis.

        La frontera expone quien fallo, no el stack trace: el detalle vive en
        `agent_errors` para el GROUP BY del monitoreo. Sin deduplicar a
        proposito — con `@degrades` cada nodo produce a lo sumo un error, asi
        que un repetido seria un bug que no conviene esconder.
        """
        return [error.agent for error in self.agent_errors]
