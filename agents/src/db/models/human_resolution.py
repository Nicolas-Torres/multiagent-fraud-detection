from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, Enum as SQLEnum, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from agents.src.db.base import Base
from agents.src.enums import HumanAction

if TYPE_CHECKING:
    from agents.src.db.models.case import Case


class HumanResolution(Base):
    __tablename__ = "human_resolutions"

    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("cases.case_id", ondelete="CASCADE"),
        primary_key=True
    )

    action: Mapped[HumanAction] = mapped_column(SQLEnum(HumanAction, native_enum=False))

    analyst_id: Mapped[str] = mapped_column(String)

    notes: Mapped[str | None] = mapped_column(Text)

    resolved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now()
    )

    case: Mapped["Case"] = relationship(back_populates="human_resolution")
