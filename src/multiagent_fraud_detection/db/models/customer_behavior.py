from decimal import Decimal

from sqlalchemy import Numeric, SmallInteger, String
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from multiagent_fraud_detection.db.base import Base


class CustomerBehavior(Base):
    __tablename__ = "customer_behaviors"

    customer_id: Mapped[str] = mapped_column(String, primary_key=True)
    usual_amount_avg: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    usual_hour_start: Mapped[int] = mapped_column(SmallInteger)
    usual_hour_end: Mapped[int] = mapped_column(SmallInteger)
    usual_countries: Mapped[list[str]] = mapped_column(ARRAY(String(2)))
    usual_devices: Mapped[list[str]] = mapped_column(ARRAY(String))
