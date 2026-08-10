"""`POST /api/v1/cases` (W0 + W1): idempotencia por `transaction_id`, y que
el grafo se agenda en segundo plano sin bloquear la respuesta.

La sesión es un doble que simula lo mínimo que Postgres haría —los defaults
de `case_id` (`uuid4`, del lado de Python) y `created_at` (`server_default`,
que acá se simula porque no hay servidor)— sin tocar la base. El flujo real
de punta a punta, con el grafo corriendo de verdad, lo verifica
`scripts/smoke_api.py`.
"""

from datetime import UTC, datetime
from uuid import uuid4

from fastapi.testclient import TestClient

from multiagent_fraud_detection.api.app import app
from multiagent_fraud_detection.api.deps import get_graph, get_graph_context, get_session
from multiagent_fraud_detection.db.models import Case
from multiagent_fraud_detection.enums import CaseStatus

PAYLOAD = {
    "transaction_id": "T-API-TEST",
    "customer_id": "CU-API-TEST",
    "amount": "50.00",
    "currency": "PEN",
    "country": "PE",
    "channel": "web",
    "device_id": "D-API-TEST",
    "timestamp": "2026-03-10T15:00:00+00:00",
    "merchant_id": "M-API-TEST",
}


class _SesionFake:
    """Simula sólo lo que `crear_caso` necesita: un `SELECT` de idempotencia,
    `add`/`commit` que aplican los defaults que Postgres aplicaría, y
    `rollback`/`refresh` como no-ops."""

    def __init__(self, existente: Case | None = None):
        self._existente = existente
        self.agregados: list = []
        self.comprometido = False

    async def scalar(self, stmt):
        return self._existente

    def add(self, obj):
        self.agregados.append(obj)

    async def commit(self):
        self.comprometido = True
        for obj in self.agregados:
            if isinstance(obj, Case):
                if obj.case_id is None:
                    obj.case_id = uuid4()
                if obj.created_at is None:
                    obj.created_at = datetime.now(UTC)

    async def refresh(self, obj):
        pass

    async def rollback(self):
        pass


class _GrafoFake:
    """No corre nada real: sólo registra si lo llamaron, para probar que el
    endpoint lo agenda sin esperarlo."""

    def __init__(self):
        self.invocado = False

    async def ainvoke(self, entrada, context):
        self.invocado = True


class _CtxManager:
    """Async context manager mínimo, para simular tanto
    `contexto.session_factory()` como `session.begin()`."""

    def __init__(self, valor):
        self._valor = valor

    async def __aenter__(self):
        return self._valor

    async def __aexit__(self, *exc):
        return False


class _SesionMarcador:
    """La sesión que ve `_marcar` (W1: `ANALYZING`, y `FAILED` si el grafo
    lanza) — no la misma que ve `crear_caso`, porque W1 abre la suya propia."""

    def __init__(self, marcas: list):
        self._marcas = marcas

    def begin(self):
        return _CtxManager(self)

    async def execute(self, stmt):
        self._marcas.append(stmt)


class _ContextoFake:
    def __init__(self):
        self.marcas: list = []

    def session_factory(self):
        return _CtxManager(_SesionMarcador(self.marcas))


def _override(sesion: _SesionFake, grafo: _GrafoFake, contexto: _ContextoFake):
    async def _sesion_override():
        yield sesion

    app.dependency_overrides[get_session] = _sesion_override
    app.dependency_overrides[get_graph] = lambda: grafo
    app.dependency_overrides[get_graph_context] = lambda: contexto


def test_transaccion_nueva_devuelve_202_y_agenda_el_grafo():
    sesion = _SesionFake(existente=None)
    grafo = _GrafoFake()
    contexto = _ContextoFake()
    _override(sesion, grafo, contexto)
    try:
        with TestClient(app) as client:
            respuesta = client.post("/api/v1/cases", json=PAYLOAD)
    finally:
        app.dependency_overrides.clear()

    assert respuesta.status_code == 202
    cuerpo = respuesta.json()
    assert cuerpo["status"] == "RECEIVED"
    assert sesion.comprometido
    # `TestClient` corre los `BackgroundTasks` antes de devolver la respuesta.
    assert grafo.invocado
    # W1 marcó ANALYZING antes de invocar el grafo.
    assert len(contexto.marcas) == 1


def test_transaccion_existente_devuelve_200_sin_correr_el_grafo():
    existente = Case(
        case_id=uuid4(),
        transaction_id="T-API-TEST",
        status=CaseStatus.DECIDED,
        created_at=datetime.now(UTC),
    )
    sesion = _SesionFake(existente=existente)
    grafo = _GrafoFake()
    contexto = _ContextoFake()
    _override(sesion, grafo, contexto)
    try:
        with TestClient(app) as client:
            respuesta = client.post("/api/v1/cases", json=PAYLOAD)
    finally:
        app.dependency_overrides.clear()

    assert respuesta.status_code == 200
    assert respuesta.json()["case_id"] == str(existente.case_id)
    assert not sesion.comprometido
    assert not grafo.invocado
    assert contexto.marcas == []


def test_el_grafo_que_lanza_deja_el_caso_en_failed():
    """W1: una excepción no capturada del grafo entero -no un agente
    degradado, eso ya lo atrapa `@degrades`- es lo único que escribe
    `FAILED`, y lo escribe el wrapper, no el grafo."""

    class _GrafoRoto:
        async def ainvoke(self, entrada, context):
            raise RuntimeError("el grafo entero reventó")

    sesion = _SesionFake(existente=None)
    contexto = _ContextoFake()
    _override(sesion, _GrafoRoto(), contexto)
    try:
        with TestClient(app) as client:
            respuesta = client.post("/api/v1/cases", json=PAYLOAD)
    finally:
        app.dependency_overrides.clear()

    assert respuesta.status_code == 202
    # Dos marcas: ANALYZING antes de invocar, FAILED al capturar la excepción.
    assert len(contexto.marcas) == 2
