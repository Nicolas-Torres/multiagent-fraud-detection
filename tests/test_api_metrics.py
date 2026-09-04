"""`GET /api/v1/metrics/llm` (ADR-0019): nunca toca la red real en un test.

Se mockea `_consultar_langsmith_sync` en vez de encadenar un `Client` falso
de LangSmith -mismo criterio que el resto de la suite: los gates
determinísticos no pueden depender de una salida de LLM ni de la red, y acá
tampoco de un proveedor de observabilidad de terceros.
"""

from unittest.mock import patch

from fastapi.testclient import TestClient

from multiagent_fraud_detection.api.app import app
from multiagent_fraud_detection.api.routers import metrics
from multiagent_fraud_detection.config.settings import settings
from multiagent_fraud_detection.schemas.llm_metrics import (
    LlmMetricsRead,
    LlmMetricsSummary,
    LlmNodeMetrics,
)


def _resultado_de_prueba() -> LlmMetricsRead:
    return LlmMetricsRead(
        available=True,
        project="fraud-detection",
        summary=LlmMetricsSummary(
            run_count=3,
            total_cost=0.03,
            avg_cost_per_decision=0.01,
            latency_p50_seconds=12.5,
            latency_p99_seconds=17.0,
            total_tokens=6000,
            error_rate=0.0,
        ),
        nodes=[
            LlmNodeMetrics(
                name="decision_arbiter", run_count=3,
                avg_latency_seconds=4.6, avg_tokens=1000.0, avg_cost=0.002,
            ),
        ],
    )


def _reset_cache() -> None:
    metrics._cache["data"] = None
    metrics._cache["fetched_at"] = 0.0


def _con_langsmith_configurado(tracing: bool, api_key: str | None):
    """Guarda y restaura `settings` -es un singleton de proceso, no un
    `Depends` sobreescribible-, mismo motivo que se restaura al `finally`."""
    original = (settings.langsmith_tracing, settings.langsmith_api_key)
    settings.langsmith_tracing = tracing
    settings.langsmith_api_key = api_key
    return original


def test_sin_configurar_no_llama_a_langsmith():
    original = _con_langsmith_configurado(False, None)
    _reset_cache()
    try:
        with patch.object(metrics, "_consultar_langsmith_sync") as mock_consulta:
            with TestClient(app) as client:
                respuesta = client.get("/api/v1/metrics/llm")
        mock_consulta.assert_not_called()
    finally:
        settings.langsmith_tracing, settings.langsmith_api_key = original

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["available"] is False
    assert cuerpo["summary"] is None
    assert cuerpo["nodes"] is None


def test_con_datos_expone_resumen_y_nodos_y_cachea():
    original = _con_langsmith_configurado(True, "ls-fake-key")
    _reset_cache()
    try:
        with patch.object(
            metrics, "_consultar_langsmith_sync", return_value=_resultado_de_prueba()
        ) as mock_consulta:
            with TestClient(app) as client:
                primera = client.get("/api/v1/metrics/llm")
                segunda = client.get("/api/v1/metrics/llm")
        assert mock_consulta.call_count == 1, "la segunda llamada debe venir de la caché"
    finally:
        settings.langsmith_tracing, settings.langsmith_api_key = original

    assert primera.status_code == segunda.status_code == 200
    assert primera.json() == segunda.json()
    cuerpo = primera.json()
    assert cuerpo["available"] is True
    assert cuerpo["summary"]["run_count"] == 3
    assert cuerpo["nodes"][0]["name"] == "decision_arbiter"


def test_force_salta_el_cache_y_lo_actualiza():
    original = _con_langsmith_configurado(True, "ls-fake-key")
    _reset_cache()
    try:
        primero = _resultado_de_prueba()
        segundo = _resultado_de_prueba()
        segundo.summary.run_count = 4  # type: ignore[union-attr]
        with patch.object(
            metrics, "_consultar_langsmith_sync", side_effect=[primero, segundo]
        ) as mock_consulta:
            with TestClient(app) as client:
                sin_forzar = client.get("/api/v1/metrics/llm")
                forzada = client.get("/api/v1/metrics/llm?force=true")
                # El caché quedó actualizado con el resultado forzado -un
                # tercer poll normal ya lo ve, sin pedirlo de nuevo.
                siguiente_normal = client.get("/api/v1/metrics/llm")
        assert mock_consulta.call_count == 2
    finally:
        settings.langsmith_tracing, settings.langsmith_api_key = original

    assert sin_forzar.json()["summary"]["run_count"] == 3
    assert forzada.json()["summary"]["run_count"] == 4
    assert siguiente_normal.json()["summary"]["run_count"] == 4


def test_si_langsmith_falla_no_rompe_el_endpoint():
    original = _con_langsmith_configurado(True, "ls-fake-key")
    _reset_cache()
    try:
        with patch.object(
            metrics, "_consultar_langsmith_sync", side_effect=RuntimeError("caído")
        ):
            with TestClient(app) as client:
                respuesta = client.get("/api/v1/metrics/llm")
    finally:
        settings.langsmith_tracing, settings.langsmith_api_key = original

    assert respuesta.status_code == 200
    assert respuesta.json()["available"] is False
