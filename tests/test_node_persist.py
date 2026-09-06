"""Nodo persistidor (W2): `persist_decision`.

No existía cobertura de que el `UPDATE` sobre `cases` escribiera lo que
`persist_decision` promete —el propio docstring del nodo dice "único punto
donde el grafo escribe a las tablas"—. `customer_snapshot` es el caso
concreto: `behavioral_pattern` lo calcula y viaja en el estado, pero hasta
este test nada verificaba que llegara a la fila. Sin base real: se captura
el `Update` compilado, no se ejecuta contra Postgres.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

from multiagent_fraud_detection.enums import Channel, DecisionType, Segment
from multiagent_fraud_detection.graph.nodes import persist_decision
from multiagent_fraud_detection.schemas.customer_behavior import CustomerBehaviorRead


class _CtxManager:
    def __init__(self, valor):
        self._valor = valor

    async def __aenter__(self):
        return self._valor

    async def __aexit__(self, *exc):
        return False


class _SesionFake:
    """Captura lo que `persist_decision` ejecuta, sin tocar Postgres."""

    def __init__(self):
        self.ejecutados: list = []
        self.agregados: list = []

    def begin(self):
        return _CtxManager(self)

    async def execute(self, stmt):
        self.ejecutados.append(stmt)

    def add(self, obj):
        self.agregados.append(obj)


@dataclass
class _Ctx:
    session_factory: object
    catalog: object


@dataclass
class _Rt:
    context: object


def _runtime(catalogo, sesion: _SesionFake) -> _Rt:
    return _Rt(_Ctx(session_factory=lambda: _CtxManager(sesion), catalog=catalogo))


def _estado(*, customer_snapshot=None) -> dict:
    """Un `APPROVE` limpio: sin políticas disparadas, nada que citar — pasa
    las cuatro guardas de `_verificar_invariantes` sin necesitar más armado."""
    return {
        "case_id": uuid4(),
        "decision": DecisionType.APPROVE,
        "confidence": 0.95,
        "risk_score": 0.05,
        "base_confidence": 0.95,
        "confidence_rationale": None,
        "scoring_version": "1.0",
        "retrieval_index_version": None,
        "threat_intel_version": None,
        "policies": [],
        "citations_internal": [],
        "citations_external": [],
        "pro_fraud_argument": "x",
        "pro_customer_argument": "y",
        "agent_route": [],
        "explanation_prompt_version": None,
        "explanation_customer": "z",
        "explanation_audit": "w",
        "evidence": [],
        "agent_errors": [],
        "customer_snapshot": customer_snapshot,
    }


def _perfil() -> CustomerBehaviorRead:
    return CustomerBehaviorRead(
        customer_id="CU-0001",
        usual_amount_avg=Decimal("100.00"),
        usual_hour_start=8,
        usual_hour_end=20,
        usual_countries=["PE"],
        usual_devices=["D-0001"],
        usual_channel=Channel.WEB,
        account_creation_date=date(2020, 1, 1),
        last_profile_update=datetime(2026, 1, 1, tzinfo=UTC),
        daily_limit=Decimal("500.00"),
        currency="PEN",
        timezone="America/Lima",
        segment=Segment.RETAIL,
    )


def _update_de_cases(sesion: _SesionFake):
    """El segundo `execute`: el primero es el `DELETE` de `decisions`."""
    return sesion.ejecutados[-1]


async def test_el_snapshot_del_cliente_llega_a_cases(catalogo):
    sesion = _SesionFake()
    perfil = _perfil()

    await persist_decision(_estado(customer_snapshot=perfil), _runtime(catalogo, sesion))

    valores = _update_de_cases(sesion).compile().params
    assert valores["customer_snapshot"] == perfil.model_dump(mode="json")


async def test_sin_perfil_el_snapshot_queda_nulo_no_ausente(catalogo):
    """`customer_snapshot=None` en el estado tiene que escribir `NULL`, no
    dejar el `UPDATE` sin esa clave —lo segundo conservaría lo que hubiera
    de antes en la fila, que es exactamente el bug que este test evita
    reintroducir."""
    sesion = _SesionFake()

    await persist_decision(_estado(customer_snapshot=None), _runtime(catalogo, sesion))

    valores = _update_de_cases(sesion).compile().params
    assert "customer_snapshot" in valores
    assert valores["customer_snapshot"] is None
