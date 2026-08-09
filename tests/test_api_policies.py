"""`GET /api/v1/policies`: de solo lectura sobre el catálogo (ADR-0017).

Sin sesión de base -el catálogo vive en `GraphContext`, no en Postgres-, así
que el doble es del contexto, no de la sesión.
"""

from fastapi.testclient import TestClient

from multiagent_fraud_detection.api.app import app
from multiagent_fraud_detection.api.deps import get_graph_context
from multiagent_fraud_detection.domain.catalog import Policy, PolicyCatalog, PolicyState
from multiagent_fraud_detection.enums import DecisionType


class _ContextoFake:
    def __init__(self, catalog: PolicyCatalog):
        self.catalog = catalog


def _catalogo() -> PolicyCatalog:
    return PolicyCatalog(
        version="2025.1-b1",
        reference_currency="USD",
        policies=(
            Policy(
                "FP-01", "2025.1", "texto de la norma", PolicyState.ACTIVE,
                action=DecisionType.CHALLENGE, bound_by="nicolas",
            ),
            Policy(
                "FP-10", "2025.2", "otra norma", PolicyState.EXCLUDED,
                excluded_reason="evidencia no reproducible",
            ),
        ),
    )


def test_lista_las_politicas_del_catalogo():
    app.dependency_overrides[get_graph_context] = lambda: _ContextoFake(_catalogo())
    try:
        with TestClient(app) as client:
            respuesta = client.get("/api/v1/policies")
    finally:
        app.dependency_overrides.clear()

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert len(cuerpo) == 2

    activa = next(p for p in cuerpo if p["policy_id"] == "FP-01")
    assert activa["state"] == "active"
    assert activa["action"] == "CHALLENGE"
    assert activa["evaluable"] is True

    excluida = next(p for p in cuerpo if p["policy_id"] == "FP-10")
    assert excluida["state"] == "excluded"
    assert excluida["action"] is None
    assert excluida["evaluable"] is False
    assert excluida["excluded_reason"] == "evidencia no reproducible"


def test_no_hay_endpoint_de_alta():
    """ADR-0017: `POST /api/v1/policies` no existe todavía, a propósito."""
    with TestClient(app) as client:
        respuesta = client.post("/api/v1/policies", json={})
    assert respuesta.status_code in (404, 405)
