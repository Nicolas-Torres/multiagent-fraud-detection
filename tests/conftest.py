"""Fixtures del dominio.

Todo lo de acá se construye **en memoria**: ni base, ni red, ni LLM. Es lo que
hace que esta suite corra en el CI del entregable 5 sin levantar un servicio, y
la razón por la que la capa de reglas se diseñó sin I/O.

Los objetos son los mismos schemas de la frontera (`TransactionIn`,
`CustomerBehaviorIn`), no dobles de prueba: si un test pasa con un doble pero el
schema real valida distinto, el test miente.
"""

import os

# `config/settings.py` instancia `Settings()` al importarse, asi que cualquier
# test que toque ese modulo exige `DATABASE_URL`. Sin esto, la suite dependeria
# de que exista un `.env` —falla en un clon limpio y en CI antes de levantar
# Postgres—. El valor no se usa: ningun test abre una conexion.
os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg://test:test@localhost:5432/test"
)

from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from multiagent_fraud_detection.domain.catalog import load_catalog
from multiagent_fraud_detection.schemas.customer_behavior import CustomerBehaviorIn
from multiagent_fraud_detection.schemas.transaction import TransactionIn

POLICIES = Path(__file__).resolve().parents[1] / "data" / "policies"

#: Instante de referencia: 2026-03-10 15:00 UTC = 10:00 en Lima.
T0 = datetime(2026, 3, 10, 15, 0, tzinfo=None).replace(tzinfo=datetime.now().astimezone().tzinfo)


def utc(*args) -> datetime:
    from datetime import timezone

    return datetime(*args, tzinfo=timezone.utc)


@pytest.fixture
def perfil() -> CustomerBehaviorIn:
    """Cliente diurno de Lima: opera 08–20, en PE, con un dispositivo, por web."""
    return CustomerBehaviorIn(
        customer_id="CU-0001",
        usual_amount_avg=Decimal("1000.00"),
        usual_hour_start=8,
        usual_hour_end=20,
        usual_countries=["PE"],
        usual_devices=["D-0001"],
        usual_channel="web",
        account_creation_date=date(2020, 1, 1),
        last_profile_update=utc(2026, 1, 1, 0, 0),
        daily_limit=Decimal("5000.00"),
        currency="PEN",
        timezone="America/Lima",
        segment="retail",
    )


@pytest.fixture
def tx():
    """Fábrica de transacciones. Todo tiene default; se sobreescribe lo que importa."""

    def make(**kw) -> TransactionIn:
        base = dict(
            transaction_id="T-0001",
            customer_id="CU-0001",
            amount=Decimal("100.00"),
            currency="PEN",
            country="PE",
            channel="web",
            device_id="D-0001",
            timestamp=utc(2026, 3, 10, 15, 0),  # 10:00 en Lima
            merchant_id="M-001",
        )
        return TransactionIn(**(base | kw))

    return make


@pytest.fixture(scope="session")
def catalogo():
    return load_catalog(
        POLICIES / "fraud_policies_2025.1.json",
        POLICIES / "policy_bindings_2025.1.json",
    )


__all__ = ["perfil", "tx", "catalogo", "utc", "timedelta"]
