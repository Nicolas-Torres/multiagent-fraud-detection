from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Enum as SQLEnum, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from multiagent_fraud_detection.db.base import Base
from multiagent_fraud_detection.enums import Channel


class Transaction(Base):
    __tablename__ = "transactions"

    transaction_id: Mapped[str] = mapped_column(String, primary_key=True)
    customer_id: Mapped[str] = mapped_column(String, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3))
    country: Mapped[str] = mapped_column(String(2))
    channel: Mapped[Channel] = mapped_column(SQLEnum(Channel, native_enum=False))
    device_id: Mapped[str] = mapped_column(String)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    merchant_id: Mapped[str] = mapped_column(String)
