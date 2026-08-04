from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Enum as SQLEnum, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base
from src.enums import Channel


class Transaction(Base):
    __tablename__ = "transactions"

    transaction_id: Mapped[str] = mapped_column(String, primary_key=True)

    # Sin `index=True`: el índice suelto es redundante frente al compuesto
    # `(customer_id, timestamp)` de abajo. Postgres usa la columna líder de un
    # índice compuesto para una consulta que solo filtra por ella, así que el
    # suelto costaría escrituras sin habilitar ningún plan nuevo.
    #
    # Tampoco hay FK a `customer_behaviors`: una transacción de un cliente sin
    # perfil debe poder insertarse. Ese caso no es un error, es el escenario que
    # el sistema tiene que analizar.
    customer_id: Mapped[str] = mapped_column(String)

    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3))
    country: Mapped[str] = mapped_column(String(2))
    channel: Mapped[Channel] = mapped_column(SQLEnum(Channel, native_enum=False))
    device_id: Mapped[str] = mapped_column(String)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    merchant_id: Mapped[str] = mapped_column(String)

    # Dos índices porque hay **dos ejes de acceso**, no uno.
    #
    # Por cliente: FP-04 (card testing), FP-05 (geolocalización imposible) y
    # FP-11 (fraccionamiento) reconstruyen la actividad reciente de la cuenta.
    #
    # Por dispositivo: FP-03 (velocity) cuenta transacciones del mismo
    # dispositivo *sin* filtrar por cliente. Un dispositivo usado con varias
    # cuentas es la señal, no ruido: una consulta por `customer_id` no lo vería.
    #
    # `timestamp` va segundo en ambos: la igualdad filtra primero, el rango
    # después. Al revés, el índice no serviría para acotar por cliente.
    #
    # No hay `(customer_id, merchant_id, timestamp)` para FP-11: filtra por
    # comercio en memoria sobre las filas que ya trajo el índice de cliente. Un
    # tercer índice sería escritura extra por selectividad que no se necesita.
    __table_args__ = (
        Index("ix_transactions_customer_ts", "customer_id", "timestamp"),
        Index("ix_transactions_device_ts", "device_id", "timestamp"),
    )
