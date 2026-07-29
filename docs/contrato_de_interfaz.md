# Contrato de Interfaz — Sistema Multi-Agente de Detección de Fraude
**Versión 0.3 — capa de persistencia cerrada y verificada**

> Define las **fronteras** entre el motor de agentes (yo), la infraestructura (mi
> compañero) y el dashboard del analista. 🔶 = decisión conjunta pendiente.

---

## 0. Hay dos contratos, no uno

| | Contrato Operativo | Contrato de API |
|---|---|---|
| **Frontera con** | Infraestructura (compañero) | Dashboard |
| **Qué define** | Cómo se empaqueta, ejecuta y configura | Endpoints y schemas |
| **Punto de hand-off** | **La imagen en GHCR** (tag inmutable) | El API HTTP |
| **Quién valida** | Compañero | Yo |

---

## 1. Contrato Operativo (frontera con infraestructura)

### 1.1 Reparto CI / CD

| Etapa | Responsable | Contenido |
|---|---|---|
| **CI** — build | **Yo** | Dockerfile, GitHub Actions, lint + tests, publicar imagen en **GHCR** |
| **CD** — deploy | **Compañero** | Terraform, orquestador, invocar migraciones, rollout, ConfigMaps/Secrets |

La costura no es el código ni los schemas: **es la imagen versionada en GHCR**.

### 1.2 Ejecución: una imagen, dos modos de arranque

```
# Modo servir (proceso principal)
uvicorn app.main:app --host 0.0.0.0 --port ${APP_PORT}

# Modo migrar (Job de pre-deploy, lo invoca el CD ANTES del rollout)
alembic upgrade head
```

> **No** va `alembic upgrade head` en el entrypoint normal: con N réplicas tendrías
> N migraciones concurrentes → race conditions y locks. 🔶 Cerrar en reunión.

### 1.3 Health y Readiness

| Endpoint | Chequea | Uso |
|---|---|---|
| `GET /health` | El proceso vive | liveness probe |
| `GET /ready` | Postgres responde | readiness probe |

Ambos sin autenticación, `200` cuando OK.

### 1.4 Configuración: 100% por variables de entorno

| Variable | Ejemplo |
|---|---|
| `APP_PORT` | `8000` |
| `DATABASE_URL` | `postgresql+psycopg://user:pass@host:5432/fraud` |
| `ANTHROPIC_API_KEY` | `sk-ant-...` |
| `GEMINI_API_KEY` | `...` |
| `LANGSMITH_API_KEY` | `ls-...` |
| `LANGSMITH_TRACING` | `true` |
| `LANGSMITH_PROJECT` | `fraud-detection` |
| `LOG_LEVEL` | `INFO` |

> El allowlist de búsqueda web **no** es env var → tabla gobernada (§4).

### 1.5 Empaquetado

- Build reproducible: `uv sync --frozen`.
- Tags inmutables: semver + git SHA. **Nunca `latest`** para CD. 🔶
- Plataforma `linux/amd64`. Usuario no-root. `.dockerignore` excluyendo `.git`, `.venv`, `.env`.

### 1.6 Pipeline de CI

```
lint → pytest → alembic upgrade head → alembic check → build → push a GHCR
```

> **Nuevo respecto a v0.2:** `alembic check` como gate. Retorna código distinto de
> cero si un modelo cambió sin migración correspondiente. Requiere Postgres como
> `services:` en el job.

---

## 2. Contrato de API (frontera con el dashboard)

### 2.1 Ciclo de vida del caso

**`status` (etapa del pipeline) ≠ `decision` (veredicto). Campos distintos.**

```mermaid
stateDiagram-v2
    [*] --> RECEIVED
    RECEIVED --> ANALYZING
    ANALYZING --> DECIDED: decision ∈ {APPROVE, CHALLENGE, BLOCK}
    ANALYZING --> PENDING_HUMAN: decision = ESCALATE_TO_HUMAN
    PENDING_HUMAN --> RESOLVED: el analista responde
    ANALYZING --> FAILED: error
    DECIDED --> [*]
    RESOLVED --> [*]
    FAILED --> [*]
```

### 2.2 Enums

| Enum | Valores | Caso |
|---|---|---|
| `CaseStatus` | `RECEIVED`, `ANALYZING`, `DECIDED`, `PENDING_HUMAN`, `RESOLVED`, `FAILED` | MAYÚSCULA |
| `DecisionType` | `APPROVE`, `CHALLENGE`, `BLOCK`, `ESCALATE_TO_HUMAN` | MAYÚSCULA |
| `HumanAction` | `APPROVE`, `REJECT` *(extensible: `REQUEST_INFO`)* | MAYÚSCULA |
| `Channel` | `web`, `mobile` *(extensible)* | minúscula |
| `Severity` | `low`, `medium`, `high` | minúscula |

> **Nota de implementación** (no afecta al dashboard): en Postgres se persiste el
> **nombre** del miembro (`MEDIUM`), no su valor. La frontera JSON siempre expone el
> **valor** (`"medium"`). Verificado en smoke test.

### 2.3 Endpoints

| Método | Ruta | Propósito | Body | Respuesta | Código |
|---|---|---|---|---|---|
| `POST` | `/api/v1/cases` | Ingresar transacción | `Transaction` | `CaseCreated` | `202` nuevo / `200` reintento |
| `GET` | `/api/v1/cases` | Listar/filtrar cola (HITL) | query: `status`, `limit`, `offset` | `Page[CaseSummary]` | `200` |
| `GET` | `/api/v1/cases/{case_id}` | Detalle completo | — | `CaseDetail` | `200` |
| `POST` | `/api/v1/cases/{case_id}/resolution` | Acción del analista | **`HumanResolutionIn`** | `CaseDetail` | `200` |
| `GET` | `/health` | Liveness | — | `{status}` | `200` |
| `GET` | `/ready` | Readiness (Postgres) | — | `{status}` | `200` |

### 2.4 Idempotencia en `POST /cases`

- `transaction_id` tiene **constraint único** en `cases` — garantizado por la BD,
  no por el código (`cases_transaction_id_key`).
- `transaction_id` ya existente (reintento de la pasarela): **no** se crea caso ni
  se corre el pipeline → devuelve el `case_id` existente con `200`.
- `transaction_id` nuevo: se crea el caso, arranca el grafo, `202`.

> Regla: mismo `transaction_id` = reintento (un caso). Distinto = evento real
> distinto (dos casos), aunque los demás datos sean idénticos.
> **Supuesto**: el sistema origen garantiza `transaction_id` único por transacción real.

### 2.5 Esquemas

#### `Transaction` — *único payload del `POST /cases`*

| Campo | Tipo | Validación en frontera |
|---|---|---|
| `transaction_id` | `str` | `min_length=1`; clave de idempotencia |
| `customer_id` | `str` | `min_length=1` |
| `amount` | `Decimal` | `> 0`, `max_digits=12`, `decimal_places=2` — **nunca `float`** |
| `currency` | `str` | ISO 4217, exacto 3, **normalizado a mayúsculas** |
| `country` | `str` | ISO 3166-1 α2, exacto 2, **normalizado a mayúsculas** |
| `channel` | `Channel` | enum |
| `device_id` | `str` | `min_length=1` |
| `timestamp` | `datetime` | aware, UTC |
| `merchant_id` | `str` | `min_length=1` |

#### `CustomerBehavior` — *NO viene en el request*

Vive en Postgres; el **Behavioral Pattern Agent** lo recupera por `customer_id`
dentro del grafo. En `CaseDetail` aparece como el **snapshot congelado** usado en
el análisis (§7.3).

| Campo | Tipo | Validación |
|---|---|---|
| `customer_id` | `str` | `min_length=1` |
| `usual_amount_avg` | `Decimal` | `> 0`, `max_digits=12`, `decimal_places=2` |
| `usual_hour_start` | `int` | `0–23`; `"08-20"` → `8` |
| `usual_hour_end` | `int` | `0–23`; `"08-20"` → `20` |
| `usual_countries` | `list[str]` | cada elemento ISO α2, mayúsculas; **lista vacía permitida** |
| `usual_devices` | `list[str]` | **lista vacía permitida** |

> **Semántica del rango horario**: `[start, end]` **inclusive** — `"08-20"` incluye
> las 20:45. Un cliente nocturno (`22-06`) es válido: `start > end` **no** está
> prohibido, y la lógica de comparación debe contemplar el cruce de medianoche.
>
> **Listas vacías**: "ningún dispositivo habitual" significa *todo dispositivo es
> nuevo* → eso es señal, no dato inválido.
>
> **Normalización de formato** (`"08-20"` → `(8, 20)`, `"PE"` → `["PE"]`): vive en
> el **script de seed**, no en el schema. Un adaptador por fuente; el dominio recibe
> datos canónicos. Cuantizar el promedio a 2 decimales también es tarea del seed.

#### `Decision` (salida del grafo)

| Campo | Tipo | Notas |
|---|---|---|
| `decision` | `DecisionType` | |
| `confidence` | `float` (0.0–1.0) | **híbrida**: score determinístico desde señales, ajustable por el Arbiter con justificación |
| `signals` | `list[Signal]` | orden de producción preservado |
| `citations_internal` | `list[InternalCitation]` | políticas (RAG) |
| `citations_external` | `list[ExternalCitation]` | alertas web (gobernada) |
| `debate` | `DebateSummary` | pro-fraude / pro-cliente |
| `agent_route` | `list[str]` | audit trail: qué agentes corrieron, **en orden** |
| `explanation_customer` | `str` | |
| `explanation_audit` | `str` | |
| **`decided_at`** | `datetime` | 🆕 lo acuña el servidor |

**`Signal`**: `code` (`AMOUNT_OUT_OF_RANGE`), `description`, `severity` (`Severity`)
— *sin `id`: una señal no tiene identidad expuesta al cliente.*
**`InternalCitation`**: `policy_id`, `chunk_id`, `version`
**`ExternalCitation`**: `url`, `summary`, `retrieved_at`
**`DebateSummary`**: `pro_fraud_argument`, `pro_customer_argument`

> `confidence` es `float`, no `Decimal`. El contraste con el dinero es deliberado:
> `Decimal` existe porque los montos se suman y deben cuadrar al centavo. Un score
> no se suma ni se audita contablemente.

#### `CaseDetail` — respuesta del `GET /cases/{case_id}`

| Campo | Tipo | Notas |
|---|---|---|
| `case_id` | `UUID` | generado por el servidor, ≠ `transaction_id` |
| `status` | `CaseStatus` | |
| `transaction` | `Transaction` | |
| **`customer`** | **`CustomerBehavior \| null`** | 🆕 nullable: cliente nuevo sin perfil |
| `decision` | `Decision \| null` | null hasta `DECIDED`/`PENDING_HUMAN` |
| `human_resolution` | `HumanResolutionRead \| null` | solo cuando `RESOLVED` |
| `created_at` | `datetime` | |
| `updated_at` | `datetime` | |

#### `CaseSummary` — proyección plana para la cola HITL

**No es `CaseDetail` recortado.** Es una proyección deliberada, con nombres propios
y aplanados; se construye con un factory explícito que tolera casos sin decisión.

| Campo | Tipo | Origen |
|---|---|---|
| `case_id` | `UUID` | `cases` |
| `status` | `CaseStatus` | `cases` |
| `decision` | `DecisionType \| null` | `decisions.decision` |
| `confidence` | `float \| null` | `decisions.confidence` |
| `amount` | `Decimal` | `transactions.amount` |
| `customer_id` | `str` | `transactions.customer_id` |
| `created_at` | `datetime` | `cases` |

> `decision` y `confidence` son `null` cuando el caso está en `RECEIVED`/`ANALYZING`
> —listable en la cola antes de tener veredicto—.

#### `CaseCreated` — respuesta del `POST /cases`

`case_id`, `status`, `created_at`.

#### `HumanResolutionIn` — body del `POST /cases/{id}/resolution`

| Campo | Tipo |
|---|---|
| `action` | `HumanAction` |
| `analyst_id` | `str` (`min_length=1`) |
| `notes` | `str \| null` |

#### `HumanResolutionRead` — lo que aparece en `CaseDetail`

Los tres campos anteriores **más `resolved_at`** (`datetime`, lo acuña el servidor).

#### `Page[T]` — envoltura de listados

| Campo | Tipo |
|---|---|
| `items` | `list[T]` |
| `total` | `int` |
| `limit` | `int` |
| `offset` | `int` |

### 2.6 Serialización — reglas de la frontera JSON

| Tipo Python | JSON | Ejemplo |
|---|---|---|
| `Decimal` | **string** | `"9500.00"` |
| `float` | número | `0.42` |
| `datetime` | string ISO 8601 UTC | `"2026-07-24T00:18:01.698874Z"` |
| `UUID` | string | `"00000000-...-00000000000a"` |
| `HttpUrl` | string | `"https://example.com/alerta"` |
| enum | su **valor** | `"medium"`, `"ESCALATE_TO_HUMAN"` |

> **Acción para el dashboard**: `amount` y `usual_amount_avg` llegan como **string**.
> Parsearlos como número en JS pierde centavos por la misma razón por la que no son
> `float` en Python.

### 2.7 Notas de modelado

- **`case_id` ≠ `transaction_id`**: UUID del servidor; desacopla identidad interna y habilita reintentos.
- **`amount` es `Decimal`**: los `float` pierden centavos por redondeo binario.
- **`timestamp` UTC + zona**: se guarda UTC; `usual_hours` es hora local → se asume
  `America/Lima` para v1 y se documenta el supuesto.

---

## 3. Dashboard del analista *(no prioritario en esta etapa)*

Consume el Contrato de API. Dos vistas:

**Cola** (`GET /cases?status=PENDING_HUMAN`) → `Page[CaseSummary]`.

**Detalle** (`GET /cases/{id}`) → `CaseDetail`: transacción · contexto del cliente
(contraste, **puede ser null**) · señales con severidad · citas internas (políticas
+ versión) · citas externas (URL + resumen) · debate pro/contra · confianza +
explicación de auditoría · explicación al cliente · **acciones** (Aprobar/Rechazar
+ notas → `POST .../resolution`).

> El detalle debe manejar `customer: null` mostrando "cliente sin perfil previo"
> —que es información de fraude, no un hueco—.

---

## 4. Búsqueda web gobernada — allowlist como tabla

El allowlist es **dato de gobernanza** (mutable, administrado por un humano con
auditoría), no config de infraestructura. Vive en Postgres, no en env var.

**Tabla `web_search_allowlist`**: `domain`, `added_by`, `added_at`, `active`, `reason`.

- Se **siembra** con una migración/seed.
- Se **cachea en memoria** con invalidación al escribir.
- El *enforcement* (rechazar fetch fuera de la lista + registrar la fuente para
  `citations_external`) es idéntico sin importar dónde viva la lista.

**Regla general reutilizable**: *¿es config de infraestructura (estática, por deploy)
o dato de gobernanza (mutable, con audit trail)?* Lo primero → env var. Lo segundo → tabla.

> **Pendiente de modelar.** Es la única tabla del contrato que aún no existe en BD.

---

## 5. Decisiones cerradas

| # | Decisión | Resolución |
|---|---|---|
| 1 | Cálculo de confianza | **Híbrida** (determinístico desde señales + ajuste del Arbiter) |
| 2 | Payload del `POST /cases` | **Solo `Transaction`**; el grafo recupera el perfil |
| 3 | Notificación al dashboard | **Polling** en v1; WebSocket = mejora (entregable 10) |
| 4 | Allowlist de búsqueda web | **Tabla gobernada** con audit trail |
| 5 | Duplicados | **Idempotencia** por `transaction_id` |
| 6 | 🆕 `signals` | **Tabla relacional** (unidad de evaluación) |
| 7 | 🆕 `citations_*` | **JSONB** (narrativa de auditoría) |
| 8 | 🆕 Perfil del cliente en el caso | **Snapshot congelado** en JSONB, sin FK |
| 9 | 🆕 `Decision` | **Tabla propia** con PK compartida con `cases` |

---

## 6. Pendiente de cerrar 🔶

- **Migraciones**: postura propuesta = imagen soporta `alembic upgrade head`; el CD lo invoca como Job de pre-deploy.
- **Convención de tags** de la imagen en GHCR (semver + git SHA).

---

## 7. Modelo de persistencia 🆕

> Frontera **interna**: no la ve el dashboard. Se documenta porque es donde se
> resolvió el "JSONB vs relacional" que v0.2 dejó abierto.

### 7.1 Las seis tablas

| Tabla | PK | Notas |
|---|---|---|
| `transactions` | `transaction_id` (natural) | índice en `customer_id` |
| `customer_behaviors` | `customer_id` (natural) | `varchar(2)[]` y `varchar[]` para las listas |
| `cases` | `case_id` (UUID, surrogate) | FK + **UNIQUE** en `transaction_id`; índice compuesto `(status, created_at)` |
| `decisions` | `case_id` (**PK = FK** a `cases`) | 1:1 implícito, sin constraint extra |
| `signals` | `id` (BIGSERIAL) | FK a `decisions.case_id`; índice en `code` |
| `human_resolutions` | `case_id` (**PK = FK** a `cases`) | 1:1 implícito |

Los tres hijos llevan `ON DELETE CASCADE` a nivel BD.

**Falta**: `web_search_allowlist` (§4) y las tablas del checkpointer de LangGraph
(las crea LangGraph, no Alembic).

### 7.2 Regla JSONB vs relacional vs ARRAY

| Si el contenido… | Va a |
|---|---|
| es un escalar homogéneo, se lee siempre completo, no existe sin su dueño | **`ARRAY`** |
| tiene forma anidada, se produce y se archiva, se lee entero junto al caso | **`JSONB`** |
| tiene identidad, ciclo de vida propio, o el sistema lo **mide** | **tabla** |

Destilado: **JSONB para lo que el sistema produce y archiva; relacional para lo que
el sistema mide.**

Aplicación concreta:

- `signals` → **tabla**. Son la unidad de evaluación: el harness del entregable 7
  compara esperadas vs. producidas, y el monitoreo del entregable 6 vigila su
  distribución. El índice en `code` hace que el `GROUP BY` sea instantáneo.
- `citations_internal` / `citations_external` → **JSONB**. Narrativa de auditoría:
  se leen enteras junto al caso, nunca solas.
- `agent_route` → **`varchar[]`**. Secuencia de escalares donde el **orden es la
  información**.
- `debate` → **dos columnas `Text` planas**. Objeto de dos campos fijos que no va a
  crecer; JSONB solo agregaría indirección. Se recompone como objeto en la frontera.

> **JSONB no significa "sin schema"**: significa que el schema vive en Pydantic en
> vez de en el DDL. `InternalCitation`, `ExternalCitation` y `DebateSummary` son el
> contrato de forma de esas columnas, de ida y de vuelta.

### 7.3 El snapshot congelado

`cases.customer_snapshot` es JSONB **nullable**, no un FK a `customer_behaviors`.

> **Congela lo mutable, referencia lo inmutable.**

Una transacción es un evento: nunca se actualiza, así que un FK siempre devuelve lo
que se usó para decidir. Un perfil de comportamiento **sí muta**: un FK haría que un
caso de enero mostrara el perfil de marzo → auditoría rota.

Consecuencia: `customer_behaviors` es "estado actual" plano, **sin versionado**. La
historia la guarda el caso.

Corolario: **no hay FK de `transactions.customer_id` a `customer_behaviors`**. Una
transacción de un cliente sin perfil debe poder insertarse; ese caso no es un error,
es el escenario que el sistema tiene que analizar.

### 7.4 Convenciones de persistencia

- **Enums — Opción A**: `native_enum=False`, sin CHECK a nivel BD. Validación en
  boundary Pydantic + capa in-Python de SQLAlchemy. Motivo: el autogenerate de
  Alembic no rastrea CHECK de enums no-nativos → un constraint desincronizado da
  falsa seguridad. Aplica a los cinco enums.
- **Sin `CheckConstraint`** en general: `alembic check` y `--autogenerate` tienen un
  punto ciego con ellos; requieren migración manual. Con un solo escritor (la app),
  el boundary cubre las rutas reales.
- **Nulabilidad** sale del tipo `Mapped[...]`, nunca `nullable=False` explícito.
- **`lazy="selectin"`** en todas las relaciones: obligatorio en async, el lazy
  loading por defecto lanza `MissingGreenlet`. Se sobreescribe por consulta cuando
  la cola no necesita los hijos.
- **`model_dump(mode="json")`** al escribir Pydantic a JSONB: en modo Python,
  `HttpUrl` y `datetime` no son serializables por psycopg.
- **PK surrogate**: UUID cuando la identidad **viaja al cliente** (`case_id` va en la
  URL); entero autoincremental cuando es interna (`signals.id`, que además preserva
  el orden de inserción gratis).
- **Mutación in situ no se detecta**: `obj.lista.append(x)` no marca el objeto como
  sucio en `ARRAY` ni en JSONB. Reasignar la colección completa.
- **`onupdate=func.now()`** se dispara en Python, no en la BD. Un `UPDATE` por SQL
  crudo no toca `updated_at`.
- **`now()` de Postgres es `transaction_timestamp()`**: todo lo insertado en un mismo
  commit comparte instante. `decided_at - created_at` mide latencia real solo porque
  en producción son transacciones distintas.

### 7.5 Cadena de migraciones

```
c558fd490ae6  (pgvector)
   → b2a8d4bf4ee2  (transactions)
      → 97de35e4842b  (customer_behaviors)
         → ac3bc6c8573d  (cases, decisions, signals, human_resolutions)  ← head
```

---

**Estado**: v0.3 — persistencia cerrada y verificada contra Postgres.
**Valida el compañero**: §1. **Valido yo**: §2–§4, §7.
