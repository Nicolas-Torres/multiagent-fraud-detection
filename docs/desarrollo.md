# Desarrollo

Para quien va a trabajar en el código: cómo levantarlo, cómo se verifica, cómo se
regeneran los artefactos derivados y dónde está cada documento. La vista general
está en el [README](../README.md).

---

## Puesta en marcha

Requisitos: Python 3.12, [uv](https://docs.astral.sh/uv/getting-started/installation/),
Node 22 y Docker.

```bash
# 1. Dependencias
uv sync

# 2. Configuración
cp .env.example .env

# 3. Base de datos
docker compose up -d

# 4. Migraciones
uv run alembic upgrade head

# 5. Dataset, catálogo e índice vectorial
uv run python scripts/seed.py

# 6. La API
uv run uvicorn multiagent_fraud_detection.api.app:app --reload
```

`.env` trae valores por defecto que funcionan tal cual en local. `DATABASE_URL`
y `ENVIRONMENT` bastan para levantar la API y correr el grafo. Sin
`GEMINI_API_KEY` no hay índice vectorial: las citas obligatorias se resuelven
igual, pero el descubrimiento queda vacío. Sin `ANTHROPIC_API_KEY` no hay debate
ni explicación por LLM, y el árbitro no puede juzgar: **todo caso termina en
`ESCALATE_TO_HUMAN`** con el piso determinístico (`_decision_arbiter_impl` en
`graph/nodes.py`).

El dashboard corre aparte, con el backend levantado (proxy de `/api` a :8000):

```bash
cd dashboard
npm ci
npm run dev          # http://localhost:5173
```

---

## Verificación

### Gates determinísticos — sin red, sin base

```bash
uv run pytest
uv run python scripts/check_policies.py                        # 7000/7000
uv run python scripts/export_data_model_diagram.py --check
uv run python scripts/validate_dataset.py
```

### Gates contra la base

```bash
docker compose up -d && uv run alembic upgrade head && uv run python scripts/seed.py

uv run python scripts/check_policies.py --source=db   # el catálogo desde Postgres
uv run python scripts/check_retrieval.py              # ablación del descubrimiento
```

> `check_policies.py` afirma explícitamente que FP-10 **no** dispara sobre el
> dataset, incluso saturado con un indicador por emisor fechado hoy: las 7 000
> transacciones son de diciembre de 2025 y la ventana de 24 h se resuelve
> *as-of* contra el cargo, así que un indicador capturado hoy queda a ocho
> meses. No es una omisión — es una propiedad del dato, afirmada, no supuesta.

### Smoke tests

```bash
uv run python scripts/smoke_read.py             # round-trip de la capa Read
uv run python scripts/smoke_seed.py             # verifica lo que quedó en la base tras el seed
uv run python scripts/smoke_graph.py            # supersteps, reducers, input_schema
uv run python scripts/smoke_degradation.py      # un agente caído no aborta el grafo
uv run python scripts/smoke_persistence.py      # un reintento no duplica señales
uv run python scripts/smoke_catalog_sources.py  # archivo y base dan el mismo catálogo
uv run python scripts/smoke_retrieval.py        # la búsqueda no mezcla generaciones
uv run python scripts/smoke_threat_intel.py     # el fetch es idempotente; el lookup no mezcla snapshots
uv run python scripts/smoke_agents.py           # agentes determinísticos contra Postgres, comparados con el ground truth
uv run python scripts/smoke_decision.py         # incluye el caso que pasa de APPROVE a CHALLENGE, y el Arbiter LLM decidiendo sobre el piso
uv run python scripts/smoke_api.py              # la API de punta a punta por HTTP, TestClient sobre la app real
```

### Datos de demo para el dashboard

```bash
uv run python scripts/seed_dashboard_fixtures.py  # 25 casos, todo estado × veredicto relevante
uv run python scripts/seed_showcase.py            # 5 casos reales, corridos de punta a punta con LLM real
uv run python scripts/seed_diverse_scenarios.py   # candidatos "ejecutar en vivo", sin gastar LLM en elegirlos
```

### Evaluación no bloqueante

```bash
uv run --group eval python scripts/eval_golden_set.py [--dry-run]
```

Calidad del debate y del juicio del Arbiter con DeepEval sobre un golden set
curado a mano (`data/eval/golden_set_llm_agents.json`). Reporta, no bloquea —
`deepeval` vive en el grupo opt-in `eval`, fuera de `uv sync` por defecto.
Deuda declarada por [ADR-0013](adr/0013-que-se-mide-con-metricas-duras-y-que-con-llm-as-judge.md).

### Regenerar artefactos derivados

```bash
uv run python scripts/export_graph_diagram.py        # requiere conexión
uv run python scripts/export_data_model_diagram.py   # requiere conexión
uv run python scripts/index_policies.py              # índice vectorial
uv run python scripts/generate_data.py               # perfiles y transacciones
uv run python scripts/build_ground_truth.py          # etiquetas del harness
```

Todos los generadores son deterministas: `git diff --exit-code` después de
regenerar es una guarda válida de CI.

---

## Diagramas

| Archivo | Origen | Vigencia |
|---|---|---|
| `graph_topology.png` | generado del grafo compilado | automática |
| `data_model.png` · `.mmd` | generado de `Base.metadata` | automática, con `--check` |
| `c4-context.png` · `c4-container.png` | generado de `likec4/c4-container.c4` — **vista C4 vigente** | se revisa al cerrar etapa |
| `ciclo-de-vida-likec4.png` | generado de `likec4/ciclo-de-vida.c4` — vista dinámica (secuencia) | se revisa al cerrar etapa |
| `ciclo-de-vida-mermaid.png` · `ciclo-de-vida.mmd` | curado a mano, en Mermaid — mismo contenido que la de arriba, otra notación (`scripts/export_c4_diagrams.py`) | se revisa al cerrar etapa |
| `citacion-internal.drawio` | a mano | se revisa al cerrar etapa |
| `capa1-infra.drawio` | a mano — **histórico de la etapa 1**, no se actualiza | congelado |
| `transaction-flow.drawio` | a mano — apoyo de la etapa 1 | congelado |

Lo que se genera no deriva; lo que se dibuja a mano sí. `modelo-datos.drawio` se
había atrasado dos etapas antes de que alguien lo notara, y por eso el modelo de
datos pasó a generarse. Los que siguen a mano son los que codifican **juicio**
—qué está construido, qué garantiza cada camino— y no estructura.

`c4-container`/`c4-context`/`ciclo-de-vida-likec4` son un caso intermedio: el
PNG se genera (`npx likec4@latest export png docs/diagrams/likec4 -o
docs/diagrams`), pero la fuente en `docs/diagrams/likec4/*.c4` sigue siendo a
mano — el juicio vive ahí, no en el render. `ciclo-de-vida` convive a propósito
en dos notaciones: estructura y comportamiento en runtime son preguntas
distintas (ver "Describing Agentic AI Systems with C4", arXiv:2603.15021), y
acá además sirve para comparar en la práctica LikeC4 (vista dinámica nativa)
contra Mermaid (nativo en GitHub y en Claude Code, sin instalar nada) sobre el
mismo contenido real.

La documentación sigue **C4** (Context → Container → Component → Code) como
columna estructural, más vistas dinámicas, y se escribe incrementalmente al
cerrar cada etapa.

---

## Mapa de la documentación

- **[Contrato de interfaz](contrato_de_interfaz.md)** — las dos fronteras
  del sistema: la operativa (empaquetado, configuración, health) y la de API
  (endpoints y schemas). Incluye el modelo de persistencia.
- **[Trazabilidad](trazabilidad.md)** — el mapa rúbrica → evidencia, con
  los desvíos declarados frente al enunciado.
- **[Catálogo de políticas](catalogo_de_politicas.md)** — las once
  políticas, su estado y su vinculación ejecutable.
- **[Briefing del dashboard](briefing_dashboard.md)** — qué muestra cada
  vista al analista y por qué.
- **[`data/README.md`](../data/README.md)** — el dataset sintético: esquema de los tres
  archivos, semántica de las etiquetas, confusores y limitaciones.
- **[CHANGELOG](CHANGELOG.md)** — qué cambió entre versiones del contrato y
  por qué.
- **[ADR](adr/)** — decisiones de arquitectura, cada una con la alternativa
  que se descartó.
- **[Reviews](reviews/)** — cierres de etapa, en orden cronológico.
- **[Evaluaciones](evaluaciones/)** — modelos alternativos para el árbitro
  (Jev, Sonnet 5.5) y la consistencia del árbitro, con sus mediciones.
- **[Enmiendas pendientes](enmiendas_pendientes.md)** — lo que va hacia la
  próxima versión del contrato.
- **[Runbook de base nueva](runbook_base_nueva.md)** — poner en marcha una
  base vacía: crear, verificar, migrar, sembrar y comprobar.
- **[Runbook de Azure](runbook_azure_setup.md)** · **[Runbook de GCP](runbook_gcp_setup.md)**
  — cómo se armó cada infraestructura, comando por comando.
- **[Arquitectura](arquitectura.md)** — topología del grafo, modelo de datos,
  citas internas y sellos de auditoría.
- **[Incidentes](incidentes/)** — incidentes de producción, con causa y arreglo.

---

## Etapas construidas

Cada etapa cerró con un acta en [reviews/](reviews/), en orden.

| Capa | Estado |
|---|---|
| Infraestructura local (Postgres + pgvector, migraciones) | ✅ |
| Modelo de dominio: 14 tablas, schemas de frontera | ✅ |
| Esqueleto del grafo: estado, topología, degradación | ✅ |
| Persistencia de la decisión | ✅ |
| Dataset sintético y ground truth | ✅ |
| Seed de la base desde el dataset | ✅ |
| Agentes determinísticos (Context, Behavioral, Aggregation) | ✅ |
| Catálogo de políticas en Postgres (documento + vinculación) | ✅ |
| Índice vectorial de políticas, versionado y sellado | ✅ |
| RAG de políticas internas: autorización + descubrimiento | ✅ |
| Arbiter determinístico (brazo de control del entregable 7) | ✅ |
| Explicabilidad: auditoría por plantilla, cliente por LLM | ✅ |
| Tabla `web_search_allowlist` | ✅ |
| Búsqueda web gobernada + Threat Intel Agent | ✅ |
| Agentes con LLM (Debate x2, Arbiter agéntico) | ✅ |
| API FastAPI + HITL | ✅ |
| Dashboard del analista (frontend) | ✅ |
| CI, imagen y despliegue | ✅ |
| Observabilidad: LangSmith por nodo, OpenTelemetry + Grafana local | ✅ |
| Operación en producción: techos de uso y gasto, 13 incidentes documentados | ✅ |
| Despliegue sin credenciales personales: OIDC y promoción por digest | ✅ |
| Criterio sobre modelos: alternativas evaluadas y consistencia del árbitro | ✅ |
