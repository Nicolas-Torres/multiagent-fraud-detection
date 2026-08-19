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

import pytest
from fastapi.testclient import TestClient

from multiagent_fraud_detection.api.app import app
from multiagent_fraud_detection.api.deps import get_graph, get_graph_context, get_session
from multiagent_fraud_detection.api.routers import cases as cases_router
from multiagent_fraud_detection.db.models import Case
from multiagent_fraud_detection.enums import CaseStatus


@pytest.fixture(autouse=True)
def _sin_cooldown_previo():
    """El cooldown de la demo vive en un dict a nivel de módulo — sin
    limpiarlo, el orden de los tests decidiría cuál ve un escenario "usado"
    por otro test, no el código bajo prueba."""
    cases_router._ultima_corrida_por_escenario.clear()
    yield
    cases_router._ultima_corrida_por_escenario.clear()

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
    endpoint lo agenda sin esperarlo. `astream` -no `ainvoke`- porque W1
    consume el grafo en modo streaming desde ADR-0018; por defecto entrega
    un único paso, suficiente para las pruebas que no miran el streaming en
    sí (esas usan `test_case_progress.py`)."""

    def __init__(self, pasos: list[dict] | None = None):
        self.invocado = False
        self._pasos = pasos if pasos is not None else [{"transaction_context": {}}]

    async def astream(self, entrada, context, stream_mode):
        self.invocado = True
        for paso in self._pasos:
            yield paso


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
        async def astream(self, entrada, context, stream_mode):
            raise RuntimeError("el grafo entero reventó")
            yield  # pragma: no cover - nunca se alcanza; hace de esto un generador

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


def _payload_live(transaction_id: str) -> dict:
    return {**PAYLOAD, "transaction_id": transaction_id}


def test_segundo_disparo_del_mismo_escenario_da_429():
    sesion = _SesionFake(existente=None)
    grafo = _GrafoFake()
    contexto = _ContextoFake()
    _override(sesion, grafo, contexto)
    try:
        with TestClient(app) as client:
            primera = client.post("/api/v1/cases", json=_payload_live("LIVE-approve-1"))
            segunda = client.post("/api/v1/cases", json=_payload_live("LIVE-approve-2"))
    finally:
        app.dependency_overrides.clear()

    assert primera.status_code == 202
    assert segunda.status_code == 429
    # El grafo sólo corrió una vez: la segunda ni siquiera llegó a agendarse.
    assert grafo.invocado
    assert len(contexto.marcas) == 1


def test_otro_escenario_no_se_ve_afectado_por_el_cooldown_del_primero():
    sesion = _SesionFake(existente=None)
    grafo = _GrafoFake()
    contexto = _ContextoFake()
    _override(sesion, grafo, contexto)
    try:
        with TestClient(app) as client:
            client.post("/api/v1/cases", json=_payload_live("LIVE-approve-1"))
            otro = client.post("/api/v1/cases", json=_payload_live("LIVE-challenge-1"))
    finally:
        app.dependency_overrides.clear()

    assert otro.status_code == 202


def test_transaction_id_sin_prefijo_live_nunca_tiene_cooldown():
    """El contrato documentado de `POST /cases` no sabe que este cooldown
    existe — sólo lo ven los `transaction_id` que arma el propio frontend
    de la demo."""
    sesion = _SesionFake(existente=None)
    grafo = _GrafoFake()
    contexto = _ContextoFake()
    _override(sesion, grafo, contexto)
    try:
        with TestClient(app) as client:
            primera = client.post("/api/v1/cases", json=_payload_live("T-REAL-1"))
    finally:
        app.dependency_overrides.clear()

    assert primera.status_code == 202

    sesion2 = _SesionFake(existente=None)
    grafo2 = _GrafoFake()
    contexto2 = _ContextoFake()
    _override(sesion2, grafo2, contexto2)
    try:
        with TestClient(app) as client:
            segunda = client.post("/api/v1/cases", json=_payload_live("T-REAL-2"))
    finally:
        app.dependency_overrides.clear()

    assert segunda.status_code == 202
