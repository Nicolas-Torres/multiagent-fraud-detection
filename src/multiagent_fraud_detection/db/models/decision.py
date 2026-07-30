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
