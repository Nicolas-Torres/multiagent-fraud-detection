# Repaso — Etapa "API + HITL"
**Sistema Multi-Agente de Detección de Fraude · handoff de continuidad**

> Documento de cierre de etapa. Destila lo decidido y construido en
> `feature/api-hitl`, para retomar en el chat siguiente con el contexto ya
> condensado.
>
> Predecesor: `08-llm-agents.md`.
> Decisión de fondo: `adr/0017-*`.

---

## 1. Qué se cerró en esta etapa

La **frontera HTTP**: los cuatro puntos de escritura del contrato (W0–W3,
§7.3) tienen ahora cada uno su endpoint o su wrapper, más los dos de sólo
lectura para el compositor del dashboard. A diferencia de las tres etapas
anteriores, ésta fue mayormente **implementación de lo ya especificado**
—el contrato trae los endpoints desde v0.2— no diseño desde cero.

| Pieza | Archivo | Verificado |
|---|---|---|
| Esqueleto FastAPI: `lifespan`, `/health`, `/ready` | `api/app.py`, `api/deps.py` | 3 tests, con y sin Postgres real |
| `POST /cases` (W0) + wrapper de segundo plano (W1) | `api/routers/cases.py` | 3 tests |
| `GET /cases`, `GET /cases/{id}` | `api/routers/cases.py` | 4 tests |
| `POST /cases/{id}/resolution` (W3) | `api/routers/cases.py` | 3 tests |
| `GET /policies` (sólo lectura, ADR-0017) | `api/routers/policies.py`, `schemas/policy.py` | 2 tests |
| `GET /predicates` | `api/routers/predicates.py`, `schemas/predicate.py` | 4 tests |
| Smoke end-to-end sobre la app real | `scripts/smoke_api.py` | corrida real, Postgres + grafo real |

**Sin migraciones.** El modelo de datos ya traía las columnas y constraints
que la API necesitaba (`cases.transaction_id` único, `ix_cases_status_created_at`)
desde la etapa del esqueleto del grafo.

---

## 2. El giro: el contrato especificaba W1 con más precisión de la que el primer borrador implementó

El primer `_correr_grafo` sólo hacía `try: await graph.ainvoke(...) except:
log`. Funcionaba —el caso llegaba a `DECIDED`— pero releer §7.3 del contrato
mostró que W1 tiene una responsabilidad más específica: escribir
`status = ANALYZING` **antes** de invocar el grafo (para distinguir
"aceptado", que escribe W0, de "corriendo") y ser el **único** lugar que
escribe `FAILED` —ningún nodo lo hace, porque un agente caído degrada, no
aborta—.

Sin esa escritura de `ANALYZING`, un caso que tardara en procesarse se vería
idéntico en `GET /cases` a uno que todavía no arrancó, y el dashboard no
tendría forma de distinguir "en cola" de "corriendo". El contrato lo nombra
como uno de los cuatro puntos de escritura por una razón concreta —*"un
observador externo necesita ver algo en ese instante"*— y el primer borrador
lo omitía por completo.

La lección: cuando el contrato ya especifica el comportamiento con esa
precisión, la implementación tiene que releerlo como especificación, no
como inspiración general. La tabla de §7.3 no es prosa de contexto, es una
lista de comportamientos exigidos.

---

## 3. Las decisiones jugosas y su porqué

### 3.1 `PolicyRead` y `PredicateSpec` como schemas nuevos, el resto reutilizado

El contrato nombraba los dos tipos desde v0.2 sin especificar sus campos —a
diferencia de `Transaction`/`Decision`, que sí tenían tablas de campos
completas—. `CaseCreated`, `CaseDetail`, `CaseSummary`,
`HumanResolutionIn/Read` y `Page[T]` ya existían de la etapa del esqueleto
del grafo, sin consumidor hasta ahora. Diseñar los dos schemas faltantes fue
la única pieza de diseño real de la etapa, y quedó documentada en el
contrato (§2.5, enmienda de v0.10) para que deje de ser un detalle de
implementación no declarado.

### 3.2 La idempotencia de `POST /cases` no se resuelve con un solo `SELECT`

Un check-then-insert ingenuo —`SELECT`, si no existe `INSERT`— tiene una
condición de carrera real: dos requests con el mismo `transaction_id` casi
en simultáneo pueden pasar los dos el `SELECT` antes de que cualquiera
commitee. La unicidad la garantiza la base
(`cases_transaction_id_key`), no el chequeo en Python, así que el endpoint
atrapa `IntegrityError` y, si dispara, relee y devuelve `200` con el caso
que sí ganó la carrera — en vez de dejar que la excepción se propague como
un `500` para el perdedor de una condición que no es un error real.

### 3.3 `GET /predicates` no lleva `Depends`

Todos los demás endpoints inyectan sesión y/o `GraphContext`. Éste no: la
biblioteca de predicados (`domain.predicates.LIBRARY`) es un diccionario a
nivel de módulo, poblado al importar, sin base ni archivo de por medio. Es
la misma clase de dato que el catálogo —estático, releído en cada arranque
del proceso, no del request— pero un nivel más simple: ni siquiera el paso
de re-leer un archivo.

### 3.4 `TestClient` corre los `BackgroundTasks` antes de devolver la respuesta

Es lo que hace posible probar `POST /cases` de punta a punta sin mocks de
tiempo ni polling en la suite de `pytest`: para cuando `client.post(...)`
retorna, W1 ya corrió. Es también la razón por la que `smoke_api.py` no
necesita levantar un servidor real con `uvicorn` en un subproceso —mismo
criterio que el resto de los smokes del proyecto, que verifican "de punta a
punta" contra Postgres y los proveedores reales, nunca contra una copia de
la app en otro proceso—.

---

## 4. Convenciones nuevas fijadas

- **W1 escribe `ANALYZING` antes de invocar el grafo, y es el único lugar
  que escribe `FAILED`.** Ver §2.
- **`IntegrityError`, no sólo un `SELECT` previo, es la guarda real de
  idempotencia bajo carrera.**
- **Un endpoint que no toca base ni proveedor no necesita `Depends`**, aunque
  el resto del router sí — `GET /predicates` es el ejemplo.

### Footguns verificados en esta etapa

| Trampa | Detalle |
|---|---|
| `session.begin()` después de un `SELECT` en la misma sesión | SQLAlchemy 2.0 auto-inicia una transacción en el primer uso ("autobegin"); un `.begin()` explícito después levanta `InvalidRequestError: A transaction is already begun`. La corrección es no volver a abrir explícitamente lo que ya se abrió solo. |
| Defaults del lado de Python (`default=uuid4`, `default=list`) no se aplican hasta el flush | Un objeto ORM construido pero nunca agregado/flusheado a una sesión real tiene esos campos en `None`, no en su valor por defecto — un doble de sesión para tests tiene que simular esa aplicación a mano, o `model_validate` falla con "no es una lista". |
| `server_default=func.now()` no vuelve al objeto Python sin `refresh()` | Con `expire_on_commit=False` (la configuración del proyecto), el objeto no se invalida solo tras el commit — pero tampoco se llena solo con lo que la base generó. Sin `session.refresh(obj)` explícito, `created_at`/`decided_at` quedan en `None` o desactualizados. |
| `app.dependency_overrides` engancha por identidad de función | Sobreescribir con una `lambda` que envuelve un generador ya instanciado (`lambda: gen(valor)`) no funciona igual que una función `async def` generadora real — FastAPI inspecciona si el *override* mismo es una función generadora, no sólo si devuelve algo iterable. |

---

## 5. Verificación de la etapa

| Gate | Resultado |
|---|---|
| `pytest` | 279 verdes, sin red y sin base (260 al cierre de la etapa anterior) — confirmado corriendo la suite completa con `docker compose stop` |
| `check_policies.py --source=db` | 7 000/7 000, sin cambios — `domain/engine.py` no se tocó |
| `smoke_decision.py` | 5 escenarios, sin cambios respecto de la etapa anterior |
| `smoke_api.py` | ingesta, idempotencia, cola, detalle, catálogo y biblioteca de predicados, contra Postgres y el grafo reales |
| `uvicorn` real (no `TestClient`) | arrancó, `/health` y `/api/v1/policies` respondieron sobre un socket real — verificación manual, no forma parte de ningún gate |
| `export_data_model_diagram.py --check` | limpio, 14 tablas (sin cambios) |
| `export_graph_diagram.py` | sin cambios — ni la topología ni los nodos del grafo se tocaron |

---

## 6. Hallazgos y deuda

### 6.1 Sin autenticación — declarado, no implementado

La rúbrica (ítem 5, Orquestación y despliegue) no la exige, y construirla
—OAuth, JWT, roles— abre preguntas de diseño (¿quiénes son los analistas?
¿SSO?) que el proyecto no resolvió en ningún otro lado. Cada endpoint queda
como punto de extensión claro, no como hueco silencioso.

### 6.2 `POST /api/v1/policies` no existe (ADR-0017)

Esperado y declarado: la Fase 3 del catálogo (tablas) es prerequisito, y no
hay necesidad real de altas dinámicas todavía —nada la consume, porque el
dashboard tampoco existe—.

### 6.3 Un restart de proceso a mitad de un caso lo deja atascado

`BackgroundTasks`, no una cola (el C4 ya declara la arquitectura como
monolito sin broker). Un caso en `ANALYZING` cuando el proceso muere se
queda ahí para siempre: nadie lo reintenta ni lo marca `FAILED`. Aceptado y
declarado desde el briefing de la etapa (§4.1), no una sorpresa de cierre.

### 6.4 Menor

- `starlette.testclient` emite `StarletteDeprecationWarning` sobre `httpx2`
  en cada test que usa `TestClient`. No se actuó: `httpx2` no es todavía una
  dependencia real de `anthropic`/`google-genai`/`langgraph-sdk`, que siguen
  atados a `httpx` clásico — migrar ahora rompería más de lo que arregla.
- El golden set y `fundamentacion_del_debate` (acta 08 §6.1, §6.3) siguen sin
  tocar; no son responsabilidad de esta etapa.

---

## 7. Mapa de archivos al cierre

```
src/multiagent_fraud_detection/
├── api/
│   ├── app.py                  # create_app(), lifespan, /health, /ready
│   ├── deps.py                 # get_session, get_graph, get_graph_context
│   └── routers/
│       ├── cases.py            # W0, W1, W3, GET /cases(/{id})
│       ├── policies.py         # GET /policies (sólo lectura)
│       └── predicates.py       # GET /predicates
└── schemas/
    ├── policy.py                # PolicyRead — nuevo
    └── predicate.py             # PredicateSpec, ParamSpecRead — nuevos

scripts/
└── smoke_api.py                 # ingesta → cola → detalle → resolución, sobre la app real

tests/
├── test_api_health.py
├── test_api_cases.py            # POST /cases
├── test_api_cases_read.py       # GET /cases, GET /cases/{id}
├── test_api_resolution.py
├── test_api_policies.py
└── test_api_predicates.py
```

---

## 8. Qué sigue

**Dashboard del analista (frontend)** — nueva fila del README, entre
"API FastAPI + HITL" y "CI, imagen y despliegue". El reto pide "web App
(Backend + Frontend)"; el contrato §3 ya especifica qué consume cada vista,
así que no es diseño desde cero. Briefing retargeteado:
`docs/briefing_api_hitl.md`.

**Deuda declarada para el informe**: sin autenticación (§6.1), sin
`POST /policies` (§6.2), sin reintento de un caso atascado por un restart de
proceso (§6.3) — las tres explícitas, ninguna es un olvido.

---

## 9. Documentación asociada

- `adr/0017-el-catalogo-por-api-es-de-solo-lectura-hasta-la-fase-3.md`
- `enmiendas_pendientes.md` — vacío tras publicar; una enmienda hacia v0.10, en `CHANGELOG.md`
- `08-llm-agents.md` — etapa anterior
- `briefing_api_hitl.md` — hacia adelante, retargeteado a esta misma etapa antes de empezarla, ahora apunta a la siguiente
