"""`GET /api/v1/predicates`: la biblioteca, tal cual la ve el compositor del
dashboard. Sin doble: `LIBRARY` es estática y no toca ni base ni red, así
que probarla contra la real es la prueba correcta, no una excepción a la
regla de "sin red ni base" — nada de esto sale del proceso.
"""

from fastapi.testclient import TestClient

from multiagent_fraud_detection.api.app import app
from multiagent_fraud_detection.domain.predicates import LIBRARY


def test_lista_toda_la_biblioteca():
    with TestClient(app) as client:
        respuesta = client.get("/api/v1/predicates")

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert len(cuerpo) == len(LIBRARY)
    assert {p["name"] for p in cuerpo} == set(LIBRARY)


def test_requires_es_una_lista_ordenada_no_un_frozenset():
    with TestClient(app) as client:
        respuesta = client.get("/api/v1/predicates")

    for predicado in respuesta.json():
        assert predicado["requires"] == sorted(predicado["requires"])


def test_los_parametros_traen_su_forma_de_validacion():
    with TestClient(app) as client:
        respuesta = client.get("/api/v1/predicates")

    con_factor = next(p for p in respuesta.json() if p["name"] == "amount_over_avg_multiple")
    spec = con_factor["params"]["factor"]
    assert spec["kind"] in ("number", "integer", "choice")
    assert spec["label"]


def test_no_expone_fn_ni_signal_crudo():
    with TestClient(app) as client:
        respuesta = client.get("/api/v1/predicates")

    for predicado in respuesta.json():
        assert "fn" not in predicado
        assert "signal" not in predicado
