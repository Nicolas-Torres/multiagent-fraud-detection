from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum as SQLEnum, ForeignKey, Index, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base
from src.enums import CaseStatus

if TYPE_CHECKING:
    from src.db.models.decision import Decision
    from src.db.models.human_resolution import HumanResolution
    from src.db.models.transaction import Transaction


class Case(Base):
    __tablename__ = "cases"

    case_id: Mapped[UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid4
    )

    transaction_id: Mapped[str] = mapped_column(
        ForeignKey("transactions.transaction_id"),
        unique=True
    )

    status: Mapped[CaseStatus] = mapped_column(SQLEnum(CaseStatus, native_enum=False))

    customer_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now()
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now()
    )

    transaction: Mapped["Transaction"] = relationship(lazy="selectin")

    decision: Mapped["Decision | None"] = relationship(
        back_populates="case",
        cascade="all, delete-orphan",
        lazy="selectin"
    )
    
    human_resolution: Mapped["HumanResolution | None"] = relationship(
        back_populates="case",
        cascade="all, delete-orphan",
        lazy="selectin"
    )

    __table_args__ = (Index("ix_cases_status_created_at", "status", "created_at"),)

    @property
    def customer(self) -> dict[str, Any] | None:
        """El contrato lo llama `customer`; en BD es el snapshot congelado."""
        return self.customer_snapshot
