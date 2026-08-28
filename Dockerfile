# syntax=docker/dockerfile:1

# Etapa 1: build del dashboard. `schema.d.ts` y `graph_topology.json` ya
# están committeados (generados contra la app real, no acá) — esta etapa
# sólo compila, no regenera tipos ni topología.
FROM node:22-alpine AS dashboard
WORKDIR /dashboard
COPY dashboard/package.json dashboard/package-lock.json dashboard/.npmrc ./
RUN npm ci
COPY dashboard/ ./
RUN npm run build


# Etapa 2: la app real. `linux/amd64`, usuario no-root, build reproducible
# con `uv sync --frozen` (contrato §1.5).
FROM python:3.12-slim AS runtime
WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Capa de dependencias primero, separada de `src/`: cambia con mucha menos
# frecuencia, así que Docker la cachea aparte del código.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src/ src/
COPY migrations/ migrations/
COPY scripts/ scripts/
# `data/` no es sólo insumo de dev: `scripts/seed.py` la lee en runtime,
# dentro del contenedor, cuando el Job de seed corre (contrato §1.2).
COPY data/ data/
COPY alembic.ini ./
RUN uv sync --frozen --no-dev

COPY --from=dashboard /dashboard/dist/ dashboard/dist/

RUN useradd --create-home appuser && chown -R appuser:appuser /app
USER appuser

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

# Modo servir (proceso principal). Los otros tres modos de arranque
# —migrar, sembrar, fetch-intel— sobreescriben este CMD como Job
# (contrato §1.2); usan la misma imagen, no una propia.
#
# `exec` adentro del `sh -c`: sin él, uvicorn queda como hijo del shell y
# nunca ve un `SIGTERM` directo — un rollout esperaría el timeout completo
# en vez de un apagado limpio. La forma JSON de afuera evita además el
# split ambiguo que Docker señala en un `CMD` en forma shell.
CMD ["sh", "-c", "exec uvicorn multiagent_fraud_detection.api.app:app --host 0.0.0.0 --port ${APP_PORT:-8000}"]
