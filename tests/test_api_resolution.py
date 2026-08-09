"""`POST /api/v1/cases/{case_id}/resolution` (W3): sólo válido sobre un caso
en `PENDING_HUMAN`. El grafo ya terminó -no hay `interrupt()` que
reanudar-, así que resolver es escribir `human_resolutions` y pasar a
`RESOLVED`, nada más.
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient

from multiagent_fraud_detection.api.app import app
from multiagent_fraud_detection.api.deps import get_session
from multiagent_fraud_detection.db.models import Case, HumanResolution, Transaction
from multiagent_fraud_detection.enums import CaseStatus, Channel

BODY = {"action": "APPROVE", "analyst_id": "AN-01", "notes": "revisado"}


class _SesionResolucion:
    def __init__(self, caso: Case | None):
        self._caso = caso
        self.agregados: list = []
        self.comprometido = False

    async def get(self, modelo, pk):
        return self._caso

    def add(self, obj):
        self.agregados.append(obj)

    async def commit(self):
        self.comprometido = True
        for obj in self.agregados:
            if isinstance(obj, HumanResolution) and obj.resolved_at is None:
                obj.resolved_at = datetime.now(UTC)

    async def refresh(self, obj):
        pass


def _override(caso: Case | None):
    async def _sesion_override():
        yield _SesionResolucion(caso)

    app.dependency_overrides[get_session] = _sesion_override


def _caso(status: CaseStatus) -> Case:
    caso = Case(
        case_id=uuid4(),
        transaction_id="T-RES-TEST",
        status=status,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    caso.transaction = Transaction(
        transaction_id="T-RES-TEST",
        customer_id="CU-TEST",
        amount=Decimal("10.00"),
        currency="PEN",
        country="PE",
        channel=Channel.WEB,
        device_id="D-TEST",
        timestamp=datetime.now(UTC),
        merchant_id="M-TEST",
    )
    caso.decision = None
    caso.human_resolution = None
    return caso


def test_resuelve_un_caso_pendiente():
    caso = _caso(CaseStatus.PENDING_HUMAN)
    _override(caso)
    try:
        with TestClient(app) as client:
            respuesta = client.post(f"/api/v1/cases/{caso.case_id}/resolution", json=BODY)
    finally:
        app.dependency_overrides.clear()

    assert respuesta.status_code == 200
    assert respuesta.json()["status"] == "RESOLVED"
    assert caso.status is CaseStatus.RESOLVED


def test_caso_inexistente_da_404():
    _override(None)
    try:
        with TestClient(app) as client:
            respuesta = client.post(f"/api/v1/cases/{uuid4()}/resolution", json=BODY)
    finally:
        app.dependency_overrides.clear()

    assert respuesta.status_code == 404


def test_caso_que_no_esta_pendiente_da_409():
    """El grafo ya decidió (`DECIDED`) o el caso ya se resolvió
    (`RESOLVED`): una resolución nueva no puede reescribir eso."""
    caso = _caso(CaseStatus.DECIDED)
    _override(caso)
    try:
        with TestClient(app) as client:
            respuesta = client.post(f"/api/v1/cases/{caso.case_id}/resolution", json=BODY)
    finally:
        app.dependency_overrides.clear()

    assert respuesta.status_code == 409
    assert caso.status is CaseStatus.DECIDED
