# Plan de ejecución — `feature/api-hitl`

**Documento efímero.** Muere al cerrar la etapa: su contenido se convierte en
`docs/reviews/09-api-hitl.md`. No sobrevive al merge.

Las decisiones de diseño están cerradas en
[ADR-0017](adr/0017-el-catalogo-por-api-es-de-solo-lectura-hasta-la-fase-3.md)
(alcance del catálogo por API) y en `docs/briefing_api_hitl.md` §4 (arranque
en segundo plano, autenticación diferida, estrategia de pruebas). Leer los dos
antes de tocar código: acá está el orden, no el porqué.

**A diferencia de las dos etapas anteriores, esta es mayormente
implementación, no diseño.** El contrato especifica endpoints y schemas desde
v0.2 (§2.3, §2.5), y la mayoría de los schemas Pydantic de frontera
(`CaseCreated`, `CaseDetail`, `CaseSummary`, `HumanResolutionIn/Read`,
`Page[T]`) **ya existen** — se escribieron en la etapa del esqueleto del
grafo, sin consumidor hasta ahora. Sólo `PolicyRead` y `PredicateSpec` son
schemas nuevos.

---

## Estado

| # | Paso | Estado |
|---|---|---|
| 1 | Esqueleto de la app FastAPI + `/health` + `/ready` | ⬜ |
| 2 | `POST /api/v1/cases` (W0) | ⬜ |
| 3 | `GET /api/v1/cases` + `GET /api/v1/cases/{case_id}` | ⬜ |
| 4 | `POST /api/v1/cases/{case_id}/resolution` (W3) | ⬜ |
| 5 | `GET /api/v1/policies` (solo lectura, ADR-0017) | ⬜ |
| 6 | `GET /api/v1/predicates` | ⬜ |
| 7 | Pruebas: `TestClient` + `smoke_api.py` | ⬜ |
| 8 | Cierre documental | ⬜ |

---

## 1. Esqueleto de la app FastAPI

- `pyproject.toml` — `fastapi`, `uvicorn[standard]` a `dependencies`; `httpx`
  a `dev` (lo pide `TestClient`).
- `src/multiagent_fraud_detection/api/__init__.py`
- `src/multiagent_fraud_detection/api/app.py` — `create_app() -> FastAPI`,
  con `lifespan` que arma un `GraphContext` **una sola vez** por proceso
  (mismo motivo que `graph/context.py` ya documenta: cargar el catálogo por
  request relee y revalida dos archivos) y lo deja en `app.state`.
- `GET /health` (liveness, sin tocar la base) y `GET /ready` (readiness,
  `SELECT 1`).
- `WindowsSelectorEventLoopPolicy` se fija acá, en el entry point — es el
  único lugar del proceso real que la necesita; los scripts sueltos la fijan
  cada uno porque cada uno *es* un proceso.

**`BackgroundTasks`, no una cola** (briefing §4.1): el C4 ya declara la
arquitectura como monolito en un solo contenedor, sin broker. Limitación
aceptada y declarada: un restart de proceso a mitad de un caso lo deja
atascado en `ANALYZING`, sin reintento automático.

```
feat(api): add the FastAPI app skeleton with health and readiness
```

---

## 2. `POST /api/v1/cases` (W0)

`src/multiagent_fraud_detection/api/routers/cases.py`.

- `transaction_id` es la clave de idempotencia (§2.4 del contrato,
  `cases_transaction_id_key` ya la garantiza la base): existente → `200` con
  el `case_id` existente, **sin** volver a correr el grafo; nuevo → inserta
  `Transaction` + `Case(status=RECEIVED)`, agenda el grafo con
  `BackgroundTasks`, `202`.
- El grafo corre con **su propia sesión** (`get_async_session` no sirve acá:
  el request ya devolvió) — mismo `GraphContext` armado en el `lifespan`.
- Body: `Transaction` (ya existe en `schemas/transaction.py`). Respuesta:
  `CaseCreated` (ya existe).

```
feat(api): add POST /cases with background graph execution
```

---

## 3. `GET /api/v1/cases` + `GET /api/v1/cases/{case_id}`

Mismo router.

- `GET /cases`: filtra por `status`, pagina con `limit`/`offset`, devuelve
  `Page[CaseSummary]` (`CaseSummary.from_case` ya existe). El índice
  `ix_cases_status_created_at` ya está pensado para esta consulta.
- `GET /cases/{case_id}`: `CaseDetail.model_validate(case)` — `Case.customer`
  ya expone el snapshot congelado con el nombre que el contrato pide.
  `404` si no existe.

```
feat(api): add the HITL queue endpoints
```

---

## 4. `POST /api/v1/cases/{case_id}/resolution` (W3)

Mismo router.

- Sólo válido sobre un caso en `PENDING_HUMAN` — otro estado, `409`.
- Inserta `HumanResolution` (`case_id`, `action`, `analyst_id`, `notes`),
  actualiza `Case.status = RESOLVED`, en una transacción.
- Body: `HumanResolutionIn` (ya existe). Respuesta: `CaseDetail`.

```
feat(api): add the human resolution endpoint
```

---

## 5. `GET /api/v1/policies`

- `src/multiagent_fraud_detection/schemas/policy.py` — `PolicyRead`: proyecta
  `domain.catalog.Policy` (`policy_id`, `version`, `state`, `action`,
  `evaluable`, `excluded_reason`). Sin `POST` (ADR-0017).
- `src/multiagent_fraud_detection/api/routers/policies.py` — lee del
  `PolicyCatalog` que ya vive en `app.state`, no de la base.

```
feat(api): add the read-only policy catalog endpoint
```

---

## 6. `GET /api/v1/predicates`

- `src/multiagent_fraud_detection/schemas/predicate.py` — `PredicateSpec`:
  proyecta `domain.predicates.Predicate` (`name`, `requires`, `severity`,
  `params` como `dict[str, ParamSpecRead]`, `description`) desde `LIBRARY`.
  Sin `fn` ni `signal` —no son serializables ni le sirven al compositor—.
- Mismo router que políticas o uno propio; a decidir al implementar según
  cuánto código comparten.

```
feat(api): add the predicate library endpoint
```

---

## 7. Pruebas

- `tests/test_api_cases.py`, `tests/test_api_policies.py`, etc. — `TestClient`
  de FastAPI, sin red, contra una base de test o con `get_async_session`
  sobreescrito por `app.dependency_overrides`. Mismo criterio de siempre: el
  gate no depende de un proveedor LLM respondiendo de una forma específica
  (`08-llm-agents.md` §2).
- `scripts/smoke_api.py` — mismo molde que `smoke_decision.py`, pero contra
  un servidor real (`uvicorn` levantado por el script o `httpx.AsyncClient`
  con `ASGITransport`, a decidir): `POST /cases` → poll `GET /cases/{id}`
  hasta `DECIDED`/`PENDING_HUMAN` → si escaló, `POST .../resolution` → `RESOLVED`.

```
test(api): cover the endpoints with TestClient and a real-server smoke
```

---

## 8. Cierre

```bash
uv run pytest
uv run python scripts/check_policies.py --source=db
uv run python scripts/smoke_decision.py
uv run python scripts/smoke_api.py
```

Después: revisar si el contrato necesita enmiendas (probablemente ninguna —
esta etapa implementa lo que §2 ya especifica, no cambia el contrato), acta
`docs/reviews/09-api-hitl.md`, tabla de estado del README (`API FastAPI +
HITL` pasa a ✅), `CHANGELOG.md` si hubo enmiendas, diagramas regenerados
(el C4 pasa `c_api` de gris a verde), briefing retargeteado hacia el
**Dashboard del analista (frontend)** — la fila `⬜` que sigue en el README,
antes de CI/despliegue—, y **borrar este archivo**.
