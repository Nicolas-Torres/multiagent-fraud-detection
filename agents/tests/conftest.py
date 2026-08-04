"""Fixtures compartidos por los tests de la capa de dominio.

Se construyen a partir de los schemas públicos (`TransactionIn`,
`CustomerBehaviorIn`) con datos explícitos, no de la base: las políticas son
funciones puras y se prueban sin red.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from src.enums import Channel, Segment
from src.schemas.customer_behavior import CustomerBehaviorIn
from src.schemas.transaction import TransactionIn


def perfil(
    *,
    customer_id="CU-TEST",
    usual_amount_avg="1000.00",
    usual_hours="08-20",
    usual_countries="PE",
    usual_devices="D-01",
    usual_channel="web",
    account_creation_date="2024-01-01",
    last_profile_update="2025-12-01T00:00:00",
    daily_limit="5000.00",
    currency="PEN",
    timezone="America/Lima",
    segment="retail",
) -> CustomerBehaviorIn:
    inicio, fin = map(int, usual_hours.split("-"))
    return CustomerBehaviorIn(
        customer_id=customer_id,
        usual_amount_avg=Decimal(usual_amount_avg),
        usual_hour_start=inicio,
        usual_hour_end=fin,
        usual_countries=[c for c in usual_countries.split(";") if c],
        usual_devices=[d for d in usual_devices.split(";") if d],
        usual_channel=Channel(usual_channel),
        account_creation_date=date.fromisoformat(account_creation_date),
        last_profile_update=datetime.fromisoformat(last_profile_update).replace(
            tzinfo=ZoneInfo(timezone)
        ),
        daily_limit=Decimal(daily_limit),
        currency=currency,
        timezone=timezone,
        segment=Segment(segment),
    )


def tx(
    *,
    transaction_id="T-TEST",
    customer_id="CU-TEST",
    amount="2000.00",
    currency="PEN",
    country="PE",
    channel="mobile",
    device_id="D-01",
    timestamp="2025-12-17T23:45:00+00:00",
    merchant_id="M-001",
) -> TransactionIn:
    return TransactionIn(
        transaction_id=transaction_id,
        customer_id=customer_id,
        amount=Decimal(amount),
        currency=currency,
        country=country,
        channel=Channel(channel),
        device_id=device_id,
        timestamp=datetime.fromisoformat(timestamp),
        merchant_id=merchant_id,
    )


def historial(rows: list[TransactionIn]) -> list[TransactionIn]:
    """Los TransactionIn del historial se tratan como filas de `transactions`."""
    return rows
