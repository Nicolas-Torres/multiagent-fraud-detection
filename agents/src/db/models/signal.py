from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import BigInteger, Enum as SQLEnum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base
from src.enums import Severity

if TYPE_CHECKING:
    from src.db.models.decision import Decision


class Signal(Base):
    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("decisions.case_id",ondelete="CASCADE"),
        index=True
    )

    code: Mapped[str] = mapped_column(String(64), index=True)

    description: Mapped[str] = mapped_column(Text)

    severity: Mapped[Severity] = mapped_column(SQLEnum(Severity, native_enum=False))

    decision: Mapped["Decision"] = relationship(back_populates="signals")
