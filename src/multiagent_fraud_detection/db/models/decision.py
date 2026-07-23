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
