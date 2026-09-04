"""`GET /api/v1/metrics/llm`: costo y latencia reales del grafo, leídos de
LangSmith (ADR-0019) — nunca de una tabla propia, no hay una segunda fuente
de verdad para lo que LangSmith ya mide mejor (percentiles, tasa de error,
costo por tarifa real del proveedor).

Nunca un 500 por esto: sin `LANGSMITH_TRACING`/`LANGSMITH_API_KEY`, o si
LangSmith no responde, el endpoint devuelve `available=False` en vez de
fallar — mismo criterio que el resto del contrato usa para "sin datos
todavía".
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from typing import Any

from fastapi import APIRouter

from multiagent_fraud_detection.config.settings import settings
from multiagent_fraud_detection.graph.nodes import (
    AGGREGATE,
    ARBITER,
    BEHAVIORAL,
    CONTEXT,
    EXPLAIN,
    PERSIST,
    POLICY_RAG,
    PRO_CUSTOMER,
    PRO_FRAUD,
    THREAT_INTEL,
)
from multiagent_fraud_detection.schemas.llm_metrics import (
    LlmMetricsRead,
    LlmMetricsSummary,
    LlmNodeMetrics,
)

router = APIRouter(tags=["metrics"])

# Los diez nodos reales del grafo -el único filtro entre las corridas hijas
# que LangSmith trae y "nodo del agente": descarta las llamadas LLM internas
# (`ChatAnthropic`, `AnthropicJudge.judge`) que ya viajan acumuladas dentro
# del nodo padre -sumarlas aparte duplicaría el costo, no lo completaría.
NODOS_DEL_GRAFO = frozenset({
    CONTEXT, BEHAVIORAL, THREAT_INTEL, POLICY_RAG, AGGREGATE,
    PRO_FRAUD, PRO_CUSTOMER, ARBITER, EXPLAIN, PERSIST,
})

CACHE_TTL_SEGUNDOS = 30.0
_cache: dict[str, Any] = {"data": None, "fetched_at": 0.0}


def _sin_datos() -> LlmMetricsRead:
    return LlmMetricsRead(available=False, project=settings.langsmith_project)


def _consultar_langsmith_sync() -> LlmMetricsRead:
    """Bloqueante a propósito -el SDK de LangSmith no es async-, por eso el
    único caller la corre con `asyncio.to_thread`: mismo criterio que todo
    cliente síncrono de proveedor en este proyecto (bloquearía el loop de
    FastAPI, y con él cualquier otro request en vuelo, si corriera directo)."""
    from langsmith import Client

    client = Client(api_key=settings.langsmith_api_key)
    project = settings.langsmith_project or "default"

    stats = client.get_run_stats(project_names=[project], is_root=True)
    run_count = int(stats.get("run_count") or 0)
    total_cost = float(stats.get("total_cost") or 0)
    resumen = LlmMetricsSummary(
        run_count=run_count,
        total_cost=total_cost,
        avg_cost_per_decision=(total_cost / run_count) if run_count else 0.0,
        latency_p50_seconds=float(stats.get("latency_p50") or 0),
        latency_p99_seconds=float(stats.get("latency_p99") or 0),
        total_tokens=int(stats.get("total_tokens") or 0),
        error_rate=float(stats.get("error_rate") or 0),
    )

    agregados: dict[str, dict[str, float]] = defaultdict(
        lambda: {"count": 0.0, "latency": 0.0, "tokens": 0.0, "cost": 0.0}
    )
    # Sin `limit`: el generador pagina solo (de a lo sumo 100 por página,
    # el máximo que acepta la API) hasta agotar el proyecto. A la escala de
    # este proyecto -una demo, no producción- eso nunca es lento; ponerle
    # un `limit` mayor a 100 no lo acota, lo rompe (la API lo rechaza como
    # tamaño de página inválido, no como tope total).
    for corrida in client.list_runs(project_name=project, is_root=False):
        if corrida.name not in NODOS_DEL_GRAFO:
            continue
        d = agregados[corrida.name]
        d["count"] += 1
        if corrida.start_time and corrida.end_time:
            d["latency"] += (corrida.end_time - corrida.start_time).total_seconds()
        d["tokens"] += corrida.total_tokens or 0
        d["cost"] += float(corrida.total_cost or 0)

    nodos = [
        LlmNodeMetrics(
            name=nombre,
            run_count=int(d["count"]),
            avg_latency_seconds=d["latency"] / d["count"],
            avg_tokens=d["tokens"] / d["count"],
            avg_cost=d["cost"] / d["count"],
        )
        for nombre, d in sorted(agregados.items())
        if d["count"] > 0
    ]

    return LlmMetricsRead(available=True, project=project, summary=resumen, nodes=nodos)


@router.get("/metrics/llm", response_model=LlmMetricsRead)
async def metricas_llm() -> LlmMetricsRead:
    """Resumen (costo, latencia, tokens, tasa de error) + desglose por nodo
    real del grafo. Cacheado en proceso (`CACHE_TTL_SEGUNDOS`) para no
    golpear la API de LangSmith en cada poll del dashboard si hay varias
    pestañas abiertas."""
    if not (settings.langsmith_tracing and settings.langsmith_api_key):
        return _sin_datos()

    ahora = time.monotonic()
    if _cache["data"] is not None and ahora - _cache["fetched_at"] < CACHE_TTL_SEGUNDOS:
        return _cache["data"]

    try:
        resultado = await asyncio.to_thread(_consultar_langsmith_sync)
    except Exception:  # noqa: BLE001 - LangSmith es observabilidad, nunca tumba el dashboard
        return _cache["data"] or _sin_datos()

    _cache["data"] = resultado
    _cache["fetched_at"] = ahora
    return resultado
