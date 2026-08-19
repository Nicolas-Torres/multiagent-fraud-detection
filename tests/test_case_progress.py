"""Registro pub-sub en memoria de ADR-0018 (`api/case_progress.py`) y el
endpoint `GET /cases/{case_id}/stream` que lo consume.

Puramente en memoria, sin red ni base — el gate de la etapa lo pide igual
para estos tests.
"""

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from multiagent_fraud_detection.api import case_progress
from multiagent_fraud_detection.api.app import app
from multiagent_fraud_detection.api.deps import get_graph_context
from multiagent_fraud_detection.db.models import Case
from multiagent_fraud_detection.enums import CaseStatus


@pytest.fixture(autouse=True)
def _registro_limpio():
    """El registro vive a nivel de módulo — un caso de un test no puede
    quedar suscrito cuando corre el siguiente."""
    case_progress._suscriptores.clear()
    yield
    case_progress._suscriptores.clear()


async def test_publicar_llega_a_un_solo_suscriptor():
    case_id = uuid4()
    cola = case_progress.suscribirse(case_id)

    case_progress.publicar(case_id, "transaction_context")

    assert await cola.get() == "transaction_context"


async def test_publicar_llega_a_varios_suscriptores_a_la_vez():
    """Dos pestañas mirando el mismo caso ven los mismos eventos, cada una
    por su propia cola -no se reparten los eventos entre sí."""
    case_id = uuid4()
    cola_a = case_progress.suscribirse(case_id)
    cola_b = case_progress.suscribirse(case_id)

    case_progress.publicar(case_id, "behavioral_pattern")

    assert await cola_a.get() == "behavioral_pattern"
    assert await cola_b.get() == "behavioral_pattern"


async def test_publicar_a_un_caso_sin_suscriptores_no_revienta():
    case_progress.publicar(uuid4(), "transaction_context")


async def test_cerrar_manda_el_sentinel_de_fin_y_limpia_el_registro():
    case_id = uuid4()
    cola = case_progress.suscribirse(case_id)

    case_progress.cerrar(case_id)

    assert await cola.get() is case_progress.FIN
    assert case_id not in case_progress._suscriptores


def test_desuscribirse_saca_la_cola_sin_afectar_a_las_demas():
    case_id = uuid4()
    cola_a = case_progress.suscribirse(case_id)
    cola_b = case_progress.suscribirse(case_id)

    case_progress.desuscribirse(case_id, cola_a)

    assert case_progress._suscriptores[case_id] == [cola_b]


def test_desuscribirse_el_ultimo_borra_la_entrada_del_caso():
    case_id = uuid4()
    cola = case_progress.suscribirse(case_id)

    case_progress.desuscribirse(case_id, cola)

    assert case_id not in case_progress._suscriptores


def test_desuscribirse_de_un_caso_desconocido_no_revienta():
    case_progress.desuscribirse(uuid4(), asyncio.Queue())


def test_orden_de_eventos_se_preserva_por_suscriptor():
    """Cada `Queue` es FIFO: los nodos llegan en el mismo orden en que el
    grafo real los termina, incluidos los de un superstep paralelo -que
    igual llegan como eventos separados, uno por dict de una sola clave."""

    async def _correr():
        case_id = uuid4()
        cola = case_progress.suscribirse(case_id)
        for nodo in ["transaction_context", "behavioral_pattern", "external_threat_intel"]:
            case_progress.publicar(case_id, nodo)
        case_progress.cerrar(case_id)

        vistos = []
        while True:
            item = await cola.get()
            if item is case_progress.FIN:
                break
            vistos.append(item)
        return vistos

    vistos = asyncio.run(_correr())
    assert vistos == ["transaction_context", "behavioral_pattern", "external_threat_intel"]


# --- El endpoint HTTP ---------------------------------------------------


class _CtxManager:
    def __init__(self, valor):
        self._valor = valor

    async def __aenter__(self):
        return self._valor

    async def __aexit__(self, *exc):
        return False


class _SesionFake:
    def __init__(self, caso: Case | None):
        self._caso = caso

    async def get(self, modelo, case_id):
        return self._caso


class _ContextoFake:
    def __init__(self, caso: Case | None):
        self._caso = caso

    def session_factory(self):
        return _CtxManager(_SesionFake(self._caso))


def _parse_sse(cuerpo: str) -> list[str]:
    """Extrae los nombres de `event:` en orden, ignorando `data:`."""
    return [
        linea.removeprefix("event: ")
        for linea in cuerpo.splitlines()
        if linea.startswith("event: ")
    ]


def _caso(status: CaseStatus) -> Case:
    return Case(
        case_id=uuid4(),
        transaction_id="T-STREAM-TEST",
        status=status,
        created_at=datetime.now(UTC),
    )


def test_stream_de_un_caso_ya_terminal_manda_done_de_una():
    caso = _caso(CaseStatus.DECIDED)
    app.dependency_overrides[get_graph_context] = lambda: _ContextoFake(caso)
    try:
        with TestClient(app) as client:
            with client.stream("GET", f"/api/v1/cases/{caso.case_id}/stream") as resp:
                cuerpo = "".join(resp.iter_text())
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert _parse_sse(cuerpo) == ["done"]
    # Se desuscribió sola: no queda nada colgando en el registro.
    assert caso.case_id not in case_progress._suscriptores


def test_stream_de_un_caso_inexistente_manda_done_de_una():
    app.dependency_overrides[get_graph_context] = lambda: _ContextoFake(None)
    try:
        with TestClient(app) as client:
            with client.stream(
                "GET", f"/api/v1/cases/{uuid4()}/stream"
            ) as resp:
                cuerpo = "".join(resp.iter_text())
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    assert _parse_sse(cuerpo) == ["done"]


async def test_stream_de_un_caso_en_curso_entrega_los_nodos_y_termina_al_cerrar():
    """No se puede simplemente `await gen.__anext__()`: para un caso en
    curso, ese primer paso queda bloqueado en `await cola.get()` hasta que
    alguien publique algo -por diseño, es la espera real del stream. Se deja
    correr el generador como tarea de fondo hasta ese punto de bloqueo, y
    recién ahí se confirma que ya quedó suscrito antes de publicar."""
    caso = _caso(CaseStatus.ANALYZING)
    contexto = _ContextoFake(caso)

    from multiagent_fraud_detection.api.routers.cases import _eventos_de_progreso

    gen = _eventos_de_progreso(caso.case_id, contexto)
    tarea = asyncio.ensure_future(gen.__anext__())

    for _ in range(5):
        await asyncio.sleep(0)
    assert caso.case_id in case_progress._suscriptores
    assert not tarea.done()

    case_progress.publicar(caso.case_id, "transaction_context")
    primer_evento = await tarea
    assert "event: node" in primer_evento
    assert '"node": "transaction_context"' in primer_evento

    case_progress.cerrar(caso.case_id)
    segundo_evento = await gen.__anext__()
    assert segundo_evento == "event: done\ndata: {}\n\n"

    with pytest.raises(StopAsyncIteration):
        await gen.__anext__()

    # `finally` corrió al agotarse el generador: nada queda suscrito.
    assert caso.case_id not in case_progress._suscriptores
