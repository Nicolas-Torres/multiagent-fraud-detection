"""`/health` y `/ready`: liveness sin tocar la base, readiness que sí -pero
por `Depends`, no por una sesión real hardcodeada, así que el test puede
sobreescribirla con un doble.

Ninguno de los dos toca Postgres: es la garantía de `uv run pytest` ("sin red
ni base") aplicada a la API. Que `/ready` responda de verdad contra Postgres
lo verifica `scripts/smoke_api.py`, no esta suite.
"""

from fastapi.testclient import TestClient

from multiagent_fraud_detection.api.app import app
from multiagent_fraud_detection.api.deps import get_session


class _SesionOK:
    async def execute(self, stmt):
        return None


class _SesionCaida:
    async def execute(self, stmt):
        raise ConnectionError("Postgres no responde")


async def _sesion_ok():
    yield _SesionOK()


async def _sesion_caida():
    yield _SesionCaida()


def test_health_no_toca_la_base():
    with TestClient(app) as client:
        respuesta = client.get("/health")
    assert respuesta.status_code == 200
    assert respuesta.json() == {"status": "ok"}


def test_ready_ok_cuando_la_sesion_responde():
    app.dependency_overrides[get_session] = _sesion_ok
    try:
        with TestClient(app) as client:
            respuesta = client.get("/ready")
        assert respuesta.status_code == 200
        assert respuesta.json() == {"status": "ok"}
    finally:
        app.dependency_overrides.clear()


def test_ready_falla_cuando_la_sesion_no_responde():
    """Un `500`, no un `200` con detalle: es la señal que un probe de
    readiness necesita, no un caso a degradar con `@degrades`."""
    app.dependency_overrides[get_session] = _sesion_caida
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            respuesta = client.get("/ready")
        assert respuesta.status_code == 500
    finally:
        app.dependency_overrides.clear()


def test_swagger_y_openapi_no_existen_en_produccion(monkeypatch):
    """ADR-0025: en producción la API es pública y sin autenticación; Swagger
    le serviría a cualquiera un formulario para disparar el grafo.

    Lo que se afirma es que no se sirve ni Swagger ni el esquema, no un código
    puntual: sin `dashboard/dist` (CI) la ruta da 404, y con `dist` (la nube,
    o una máquina que compiló el dashboard) el catch-all del SPA responde
    `index.html` con 200, que tampoco expone nada."""
    from multiagent_fraud_detection.api.app import create_app
    from multiagent_fraud_detection.config.settings import settings

    monkeypatch.setattr(settings, "environment", "production")
    cliente = TestClient(create_app())

    for ruta in ("/docs", "/redoc", "/openapi.json"):
        respuesta = cliente.get(ruta)
        cuerpo = respuesta.text.lower()
        assert "swagger" not in cuerpo and "redoc" not in cuerpo, ruta
        assert '"openapi"' not in cuerpo and '"paths"' not in cuerpo, ruta


def test_swagger_sigue_disponible_fuera_de_produccion():
    cliente = TestClient(app)

    assert cliente.get("/docs").status_code == 200
    assert cliente.get("/openapi.json").status_code == 200
