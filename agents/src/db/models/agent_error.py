from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from agents.src.db.base import Base

if TYPE_CHECKING:
    from agents.src.db.models.decision import Decision

class AgentError(Base):
    __tablename__ = "agent_errors"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("decisions.case_id", ondelete="CASCADE"),
        index=True
    )

    agent: Mapped[str] = mapped_column(String(64), index=True)

    error_type: Mapped[str] = mapped_column(String(64))

    message: Mapped[str] = mapped_column(Text)

    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    decision: Mapped["Decision"] = relationship(back_populates="agent_errors")
