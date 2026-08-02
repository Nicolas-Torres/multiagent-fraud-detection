from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Enum as SQLEnum, Numeric, SmallInteger, String
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from multiagent_fraud_detection.db.base import Base
from multiagent_fraud_detection.enums import Channel, Segment


class CustomerBehavior(Base):
    __tablename__ = "customer_behaviors"

    customer_id: Mapped[str] = mapped_column(String, primary_key=True)
    usual_amount_avg: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    usual_hour_start: Mapped[int] = mapped_column(SmallInteger)
    usual_hour_end: Mapped[int] = mapped_column(SmallInteger)
    usual_countries: Mapped[list[str]] = mapped_column(ARRAY(String(2)))
    usual_devices: Mapped[list[str]] = mapped_column(ARRAY(String))

    # --- campos de evaluación de políticas ------------------------------------
    usual_channel: Mapped[Channel] = mapped_column(
        SQLEnum(Channel, native_enum=False)
    )
    account_creation_date: Mapped[date] = mapped_column(Date)
    last_profile_update: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    daily_limit: Mapped[Decimal] = mapped_column(Numeric(12, 2))

    # --- atributos de la cuenta -----------------------------------------------
    currency: Mapped[str] = mapped_column(String(3))

    # IANA. `String(64)` porque el nombre más largo del catálogo ronda los 32
    # caracteres (`America/Argentina/Buenos_Aires`); el margen es holgura, no
    # cálculo. No es enum: el catálogo IANA cambia sin que lo decidamos nosotros.
    timezone: Mapped[str] = mapped_column(String(64))

    segment: Mapped[Segment] = mapped_column(SQLEnum(Segment, native_enum=False))
