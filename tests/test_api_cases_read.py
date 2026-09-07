"""`GET /api/v1/cases` (cola HITL) y `GET /api/v1/cases/{case_id}` (detalle).

La sesión es un doble de lectura: no aplica el `WHERE`/`LIMIT` de verdad
—eso es SQL que confiamos al motor, mismo criterio que el resto del
proyecto—, sólo prueba que el endpoint proyecta a `CaseSummary`/`CaseDetail`
correctamente y devuelve `404` cuando corresponde. El filtrado real se
verificó a mano contra Postgres y lo cubre `scripts/smoke_api.py`.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient

from multiagent_fraud_detection.api.app import app
from multiagent_fraud_detection.api.deps import get_session
from multiagent_fraud_detection.db.models import Case, Decision, Transaction
from multiagent_fraud_detection.enums import CaseStatus, Channel, DecisionType


class _ScalarsResult:
    def __init__(self, valores):
        self._valores = valores

    def all(self):
        return list(self._valores)


class _SesionLectura:
    def __init__(self, casos: list[Case]):
        self._casos = casos

    async def scalar(self, stmt):
        return len(self._casos)

    async def scalars(self, stmt):
        return _ScalarsResult(self._casos)

    async def get(self, modelo, pk):
        return next((c for c in self._casos if c.case_id == pk), None)


def _override_sesion(casos: list[Case]):
    async def _sesion_override():
        yield _SesionLectura(casos)

    app.dependency_overrides[get_session] = _sesion_override


def _tx(transaction_id: str) -> Transaction:
    return Transaction(
        transaction_id=transaction_id,
        customer_id="CU-TEST",
        amount=Decimal("120.50"),
        currency="PEN",
        country="PE",
        channel=Channel.WEB,
        device_id="D-TEST",
        timestamp=datetime.now(UTC) - timedelta(minutes=5),
        merchant_id="M-TEST",
    )


def _caso(status: CaseStatus, *, con_decision: bool = False) -> Case:
    caso = Case(
        case_id=uuid4(),
        transaction_id="T-READ-TEST",
        status=status,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    caso.transaction = _tx("T-READ-TEST")
    if con_decision:
        caso.decision = Decision(
            case_id=caso.case_id,
            decision=DecisionType.CHALLENGE,
            confidence=0.6,
            matched_policies=[],
            citations_internal=[],
            citations_external=[],
            debate_pro_fraud="x",
            debate_pro_customer="y",
            agent_route=[],
            explanation_customer="z",
            explanation_audit="w",
            decided_at=datetime.now(UTC),
        )
    caso.human_resolution = None
    return caso


def test_lista_la_cola_como_page_de_case_summary():
    casos = [_caso(CaseStatus.PENDING_HUMAN, con_decision=True)]
    _override_sesion(casos)
    try:
        with TestClient(app) as client:
            respuesta = client.get(
                "/api/v1/cases", params={"status": "PENDING_HUMAN", "limit": 10}
            )
    finally:
        app.dependency_overrides.clear()

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["total"] == 1
    assert cuerpo["limit"] == 10
    assert len(cuerpo["items"]) == 1
    assert cuerpo["items"][0]["decision"] == "CHALLENGE"
    assert cuerpo["items"][0]["confidence"] == 0.6


def test_lista_vacia_da_total_cero():
    _override_sesion([])
    try:
        with TestClient(app) as client:
            respuesta = client.get("/api/v1/cases")
    finally:
        app.dependency_overrides.clear()

    assert respuesta.status_code == 200
    assert respuesta.json() == {"items": [], "total": 0, "limit": 50, "offset": 0}


def test_detalle_de_caso_sin_perfil_muestra_customer_null():
    caso = _caso(CaseStatus.DECIDED, con_decision=True)
    _override_sesion([caso])
    try:
        with TestClient(app) as client:
            respuesta = client.get(f"/api/v1/cases/{caso.case_id}")
    finally:
        app.dependency_overrides.clear()

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["customer"] is None
    assert cuerpo["decision"]["decision"] == "CHALLENGE"


def test_caso_inexistente_da_404():
    _override_sesion([])
    try:
        with TestClient(app) as client:
            respuesta = client.get(f"/api/v1/cases/{uuid4()}")
    finally:
        app.dependency_overrides.clear()

    assert respuesta.status_code == 404


def test_vitrina_ordena_por_casos_vitrina_no_por_orden_de_llegada():
    """`GET /cases/showcase`: el orden de salida es el de `CASOS_VITRINA`
    (T-2579 antes que T-5816), no el orden en que la sesión los devuelve —
    acá deliberadamente al revés, para que el test falle si el endpoint
    dejara de reordenar."""
    caso_5816 = _caso(CaseStatus.RESOLVED)
    caso_5816.transaction_id = "T-5816"
    caso_2579 = _caso(CaseStatus.DECIDED)
    caso_2579.transaction_id = "T-2579"
    _override_sesion([caso_5816, caso_2579])
    try:
        with TestClient(app) as client:
            respuesta = client.get("/api/v1/cases/showcase")
    finally:
        app.dependency_overrides.clear()

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert [item["transaction_id"] for item in cuerpo] == ["T-2579", "T-5816"]
    assert cuerpo[0]["case_id"] == str(caso_2579.case_id)


def test_vitrina_sin_sembrar_da_lista_vacia_no_error():
    """Un entorno que todavía no corrió `seed_showcase.py` no tiene por qué
    romper — la vitrina simplemente no tiene nada que mostrar todavía."""
    _override_sesion([])
    try:
        with TestClient(app) as client:
            respuesta = client.get("/api/v1/cases/showcase")
    finally:
        app.dependency_overrides.clear()

    assert respuesta.status_code == 200
    assert respuesta.json() == []
