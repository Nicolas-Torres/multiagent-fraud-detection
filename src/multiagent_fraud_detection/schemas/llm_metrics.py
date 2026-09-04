"""Respuesta de `GET /api/v1/metrics/llm` (ADR-0019).

`available` en vez de un 404/500 cuando LangSmith no está configurado o no
responde: el endpoint nunca falla, declara el estado — mismo criterio que
el resto del contrato usa para "sin datos todavía" (ADR-0011/ADR-0012).
"""

from __future__ import annotations

from pydantic import BaseModel


class LlmMetricsSummary(BaseModel):
    run_count: int
    total_cost: float
    avg_cost_per_decision: float
    latency_p50_seconds: float
    latency_p99_seconds: float
    total_tokens: int
    error_rate: float


class LlmNodeMetrics(BaseModel):
    name: str
    run_count: int
    avg_latency_seconds: float
    avg_tokens: float
    avg_cost: float


class LlmMetricsRead(BaseModel):
    available: bool
    project: str | None = None
    summary: LlmMetricsSummary | None = None
    nodes: list[LlmNodeMetrics] | None = None
