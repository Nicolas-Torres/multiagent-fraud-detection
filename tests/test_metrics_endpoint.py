"""`GET /metrics` existe sólo fuera de producción (ADR-0034).

Lo lee el stack local de Grafana (ADR-0024). En producción respondía público,
sin que nadie lo consultara. Sin lifespan (`TestClient` sin `with`): en
producción el arranque consulta LangSmith y la base, y acá no interesa.
"""

from fastapi.testclient import TestClient

from multiagent_fraud_detection.api.app import create_app
from multiagent_fraud_detection.config.settings import settings

METRICA = "python_gc_objects_collected_total"


def _metrics_en(entorno: str, monkeypatch) -> str:
    monkeypatch.setattr(settings, "environment", entorno)
    return TestClient(create_app()).get("/metrics").text


def test_en_local_metrics_responde_prometheus(monkeypatch):
    assert METRICA in _metrics_en("development", monkeypatch)


def test_en_produccion_metrics_no_existe(monkeypatch):
    assert METRICA not in _metrics_en("production", monkeypatch)
