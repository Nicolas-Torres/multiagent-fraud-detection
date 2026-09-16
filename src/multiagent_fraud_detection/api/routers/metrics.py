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
from datetime import UTC, datetime, timedelta
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

# Los diez nodos reales del grafo, en el mismo orden que corren
# (`graph/builder.py`) -no alfabético-: el filtro entre las corridas hijas
# que LangSmith trae y "nodo del agente" (descarta las llamadas LLM internas,
# `ChatAnthropic`/`AnthropicJudge.judge`, que ya viajan acumuladas dentro del
# nodo padre -sumarlas aparte duplicaría el costo-) y el orden de la tabla a
# la vez, en vez de mantener dos listas.
ORDEN_NODOS = (
    CONTEXT, BEHAVIORAL, THREAT_INTEL, POLICY_RAG, AGGREGATE,
    PRO_FRAUD, PRO_CUSTOMER, ARBITER, EXPLAIN, PERSIST,
)
NODOS_DEL_GRAFO = frozenset(ORDEN_NODOS)

CACHE_TTL_SEGUNDOS = 30.0
_cache: dict[str, Any] = {"data": None, "fetched_at": 0.0}

# Sin acotar, `list_runs` pagina el proyecto entero: medido en real contra
# el proyecto de este portafolio, 1624 corridas tardaron 93s -exactamente
# el "casi un minuto en blanco" que se veía en el dashboard en el primer
# request después de cada deploy (el caché en proceso se resetea con cada
# revisión nueva). Acotado a 3 días: ~200 corridas, ~2s. Es una demo en
# vivo, no una serie histórica -"reciente" es la métrica que importa.
VENTANA_RECIENTE = timedelta(days=3)


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
    desde = datetime.now(UTC) - VENTANA_RECIENTE

    # `get_run_stats` pide `start_time` como string; `list_runs` (abajo) lo
    # pide como `datetime` -mismo `desde`, dos formatos, por la firma de
    # cada uno- para que el resumen y el desglose por nodo cubran la misma
    # ventana y no queden inconsistentes entre sí.
    stats = client.get_run_stats(project_names=[project], is_root=True, start_time=desde.isoformat())
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
    # `limit` de `list_runs` es tamaño de página (tope real de la API: 100,
    # la rechaza si se le pide más) — no un tope total, así que acotar sólo
    # con eso no alcanza. `start_time` sí acota el total real de corridas
    # que trae el generador, que es lo que hace rápida esta llamada.
    for corrida in client.list_runs(project_name=project, is_root=False, start_time=desde):
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
        for nombre in ORDEN_NODOS
        if (d := agregados.get(nombre)) and d["count"] > 0
    ]

    return LlmMetricsRead(available=True, project=project, summary=resumen, nodes=nodos)


async def _refrescar_cache() -> LlmMetricsRead:
    """Pide el dato fresco y lo deja en el caché — compartido entre el
    endpoint y el precalentado de arranque (`precalentar`), para no tener
    el mismo try/except duplicado en dos lugares."""
    try:
        resultado = await asyncio.to_thread(_consultar_langsmith_sync)
    except Exception:  # noqa: BLE001 - LangSmith es observabilidad, nunca tumba el dashboard
        return _cache["data"] or _sin_datos()

    _cache["data"] = resultado
    _cache["fetched_at"] = time.monotonic()
    return resultado


async def precalentar() -> None:
    """Llena el caché al arrancar el proceso, antes de que llegue el primer
    visitante — se dispara como tarea de fondo desde `lifespan` (`app.py`),
    nunca bloquea el arranque ni `/ready`. Sin esto, cada revisión nueva
    (cada deploy) resetea el caché en proceso y el primer request paga el
    costo completo de la consulta a LangSmith.

    Acotado a `environment == "production"` a propósito -mismo criterio de
    lista blanca que `permite_operaciones_destructivas`-: sin esto, cada
    `TestClient(app)` de la suite dispara `lifespan` y con él una llamada de
    red real a LangSmith en cuanto el `.env` local tiene una clave real,
    violando "pytest sin red ni base" aunque nadie lo pidiera."""
    if settings.environment == "production" and settings.langsmith_tracing and settings.langsmith_api_key:
        await _refrescar_cache()


@router.get("/metrics/llm", response_model=LlmMetricsRead)
async def metricas_llm(force: bool = False) -> LlmMetricsRead:
    """Resumen (costo, latencia, tokens, tasa de error) + desglose por nodo
    real del grafo. Cacheado en proceso (`CACHE_TTL_SEGUNDOS`) para no
    golpear la API de LangSmith en cada poll del dashboard si hay varias
    pestañas abiertas.

    `force=true` (ADR-0020) salta el caché para esa llamada puntual —lo usa
    el dashboard cuando el stream SSE de un caso avisa que terminó, para
    reflejar su costo sin esperar hasta 30s— y **actualiza** el caché con
    el resultado fresco, así el próximo poll normal de cualquier pestaña
    también se beneficia en vez de volver a pedirlo."""
    if not (settings.langsmith_tracing and settings.langsmith_api_key):
        return _sin_datos()

    ahora = time.monotonic()
    if (
        not force
        and _cache["data"] is not None
        and ahora - _cache["fetched_at"] < CACHE_TTL_SEGUNDOS
    ):
        return _cache["data"]

    return await _refrescar_cache()
