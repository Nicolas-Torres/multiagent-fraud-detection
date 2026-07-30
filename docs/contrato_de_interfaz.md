# Contrato de Interfaz — Sistema Multi-Agente de Detección de Fraude
**Versión 0.4 — grafo, scoring y trazabilidad de ejecución**

> Define las **fronteras** entre el motor de agentes (yo), la infraestructura (mi
> compañero) y el dashboard del analista. 🔶 = decisión conjunta pendiente.
>
> Qué cambió respecto de versiones anteriores: [`CHANGELOG.md`](CHANGELOG.md).

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

> `LOG_LEVEL` gobierna también el echo de SQL de SQLAlchemy: solo en `DEBUG`.
> El allowlist de búsqueda web **no** es env var → tabla gobernada (§4).

### 1.5 Empaquetado

- Build reproducible: `uv sync --frozen`.
- Tags inmutables: semver + git SHA. **Nunca `latest`** para CD. 🔶
- Plataforma `linux/amd64`. Usuario no-root. `.dockerignore` excluyendo `.git`, `.venv`, `.env`.

### 1.6 Pipeline de CI

```
lint → pytest → alembic upgrade head → alembic check → build → push a GHCR
```

> `alembic check` retorna distinto de cero si un modelo cambió sin migración
> correspondiente. Exige que la base esté en `head`, por eso el `upgrade` va
> antes. Requiere Postgres como `services:` en el job.

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

> **`PENDING_HUMAN` es estado terminal del grafo.** El análisis no queda
> suspendido esperando al analista: termina, persiste, y la resolución entra
> por HTTP (§7.3). La máquina de estados no cambia; cambia quién escribe la
> transición a `RESOLVED`.

### 2.2 Enums

| Enum | Valores | Caso |
|---|---|---|
| `CaseStatus` | `RECEIVED`, `ANALYZING`, `DECIDED`, `PENDING_HUMAN`, `RESOLVED`, `FAILED` | MAYÚSCULA |
| `DecisionType` | `APPROVE`, `CHALLENGE`, `BLOCK`, `ESCALATE_TO_HUMAN` | MAYÚSCULA |
| `HumanAction` | `APPROVE`, `REJECT` *(extensible: `REQUEST_INFO`)* | MAYÚSCULA |
| `Channel` | `web`, `mobile` *(extensible)* | minúscula |
| `Severity` | `low`, `medium`, `high` | minúscula |

> **Nota de implementación** (no afecta al dashboard): en Postgres se persiste el
> **nombre** del miembro (`MEDIUM`), no su valor. La frontera JSON siempre expone
> el **valor** (`"medium"`). Verificado en smoke test.

### 2.3 Endpoints

| Método | Ruta | Propósito | Body | Respuesta | Código |
|---|---|---|---|---|---|
| `POST` | `/api/v1/cases` | Ingresar transacción | `Transaction` | `CaseCreated` | `202` nuevo / `200` reintento |
| `GET` | `/api/v1/cases` | Listar/filtrar cola (HITL) | query: `status`, `limit`, `offset` | `Page[CaseSummary]` | `200` |
| `GET` | `/api/v1/cases/{case_id}` | Detalle completo | — | `CaseDetail` | `200` |
| `POST` | `/api/v1/cases/{case_id}/resolution` | Acción del analista | `HumanResolutionIn` | `CaseDetail` | `200` |
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
el análisis (§7.4).

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
> el **script de seed**, no en el schema. Un adaptador por fuente; el dominio
> recibe datos canónicos.

#### `Decision` (salida del grafo)

| Campo | Tipo | Notas |
|---|---|---|
| `decision` | `DecisionType` | |
| **`risk_score`** | `float \| null` (0.0–1.0) | 🆕 **sospecha**, determinístico. Ordena la cola y vigila el drift; **no** decide |
| `confidence` | `float` (0.0–1.0) | **seguridad en el veredicto autónomo** — ver nota |
| **`base_confidence`** | `float \| null` (0.0–1.0) | 🆕 la confianza antes del ajuste del Arbiter |
| **`confidence_rationale`** | `str \| null` | 🆕 justificación del ajuste; `null` = no hubo ajuste |
| **`scoring_version`** | `str \| null` | 🆕 versión de la fórmula que produjo los scores |
| `signals` | `list[Signal]` | orden determinístico fijado por Evidence Aggregation |
| `citations_internal` | `list[InternalCitation]` | políticas (RAG) |
| `citations_external` | `list[ExternalCitation]` | alertas web (gobernada) |
| `debate` | `DebateSummary` | pro-fraude / pro-cliente |
| `agent_route` | `list[str]` | rastro de **agentes**, agrupado por superstep |
| **`degraded_agents`** | `list[str]` | 🆕 agentes que fallaron; vacío = evidencia completa |
| `explanation_customer` | `str` | |
| `explanation_audit` | `str` | |
| `decided_at` | `datetime` | lo acuña el servidor |

**`Signal`**: `code` (`AMOUNT_OUT_OF_RANGE`), `description`, `severity` (`Severity`)
— *sin `id` ni procedencia: una señal no tiene identidad expuesta al cliente.*
**`InternalCitation`**: `policy_id`, `chunk_id`, `version`
**`ExternalCitation`**: `url`, `summary`, `retrieved_at`
**`DebateSummary`**: `pro_fraud_argument`, `pro_customer_argument`

##### Riesgo y confianza son dos números, no uno

| | Sospecha (`risk_score`) | Confianza (`confidence`) |
|---|---|---|
| Muchas señales graves | alta | **alta** — `BLOCK` claro |
| Ninguna señal | baja | **alta** — `APPROVE` claro |
| Señales contradictorias | media | **baja** |
| Evidencia incompleta | sin cambio | **baja** |

La sospecha es **monótona** en las severidades. La confianza tiene **forma de U**:
máxima en los dos extremos, mínima en el medio. Una función monótona no puede
producir las dos, y por eso el contrato expone ambas.

Consecuencia: con evidencia incompleta la confianza **baja** sin que el riesgo se
mueva. Una falla de agente no es evidencia de fraude.

##### La confianza es híbrida, y el rastro es auditable

`base_confidence` lo produce **código**; el Arbiter solo puede moverlo dentro de
un delta acotado. `confidence_rationale` explica el delta.

- `confidence_rationale = null` significa **una sola cosa**: no hubo ajuste.
- Si `confidence != base_confidence`, la justificación **existe** — garantizado
  por el sistema, no por convención (§7.3).

`risk_score` **no** es ajustable por el Arbiter: si un LLM pudiera moverlo,
dejaría de servir para vigilar drift (entregable 6).

##### La cita autoriza el veredicto, no lo acompaña

Las políticas internas **prescriben una acción** (*"monto > 3x y horario fuera de
rango → CHALLENGE"*), no describen riesgo. El veredicto no sale de umbralizar un
score: sale de la política que aplica.

De ahí el invariante, que es estructural y no de calidad:

> **Ningún veredicto autónomo sin respaldo interno y sin score determinístico.**
> Diferir a un humano no es un veredicto.

Formalmente, cuando `decision != ESCALATE_TO_HUMAN`:
`citations_internal` es no vacío **y** `base_confidence` no es `null`.

`ESCALATE_TO_HUMAN` queda exento: sin la excepción, un caso sin políticas
recuperadas no tendría ninguna salida posible —no podría aprobar, ni bloquear,
ni escalar—. La ausencia de respaldo *es* la razón para llamar al humano.

**El dashboard puede asumirlo**: en todo caso `DECIDED`, las citas internas no
están vacías.

##### Orden de `signals` y de `agent_route`

Ninguno de los dos es "orden de producción". Tres agentes emiten señales desde
ramas paralelas, y el orden **entre** ramas de un mismo superstep no es el de
declaración.

- **`signals`**: el orden lo fija **Evidence Aggregation** con un criterio
  determinístico y documentado. Es requisito de reproducibilidad para el harness
  del entregable 7, no cosmética.
- **`agent_route`**: es una secuencia de supersteps aplanada. El orden **entre**
  supersteps está garantizado; la adyacencia **dentro** de un grupo no implica
  precedencia causal. Un auditor que lea la ruta como cadena causal se equivocaría.

`agent_route` contiene **agentes**, no todos los nodos del grafo: el nodo que
persiste no figura. Que corrió lo prueba la existencia de la fila.

##### Degradación

Un agente que falla **no aborta el análisis**: degrada la decisión y su nombre
aparece en `degraded_agents`. El detalle de la falla (tipo, mensaje, instante) es
frontera interna (§7.2).

> `degraded_agents` vacío significa evidencia completa. **Es una garantía del
> sistema, no una convención del cliente**: el dashboard no tiene que contar
> elementos de otra lista para deducirlo.

#### `CaseDetail` — respuesta del `GET /cases/{case_id}`

| Campo | Tipo | Notas |
|---|---|---|
| `case_id` | `UUID` | generado por el servidor, ≠ `transaction_id` |
| `status` | `CaseStatus` | |
| `transaction` | `Transaction` | |
| `customer` | `CustomerBehavior \| null` | nullable: cliente nuevo sin perfil |
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
| `list[str]` | array de strings | `["external_threat_intel"]` |

> **Acción para el dashboard**: `amount` y `usual_amount_avg` llegan como **string**.
> Parsearlos como número en JS pierde centavos por la misma razón por la que no son
> `float` en Python. Los scores (`risk_score`, `confidence`, `base_confidence`)
> **sí** son números: no se suman ni se auditan contablemente.

### 2.7 Notas de modelado

- **`case_id` ≠ `transaction_id`**: UUID del servidor; desacopla identidad interna y habilita reintentos.
- **`amount` es `Decimal`**: los `float` pierden centavos por redondeo binario.
- **`timestamp` UTC + zona**: se guarda UTC. `usual_hours` es hora **local del
  cliente**; la zona sale del perfil, no de un supuesto global. 🔶 *Pendiente de
  cerrar en la etapa de dataset.*

---

## 3. Dashboard del analista *(no prioritario en esta etapa)*

Consume el Contrato de API. Dos vistas:

**Cola** (`GET /cases?status=PENDING_HUMAN`) → `Page[CaseSummary]`.

**Detalle** (`GET /cases/{id}`) → `CaseDetail`: transacción · contexto del cliente
(contraste, **puede ser null**) · señales con severidad · citas internas (políticas
+ versión) · citas externas (URL + resumen) · debate pro/contra · riesgo y
confianza + explicación de auditoría · explicación al cliente · **acciones**
(Aprobar/Rechazar + notas → `POST .../resolution`).

> El detalle debe manejar `customer: null` mostrando "cliente sin perfil previo"
> —que es información de fraude, no un hueco—, y `degraded_agents` no vacío
> mostrando qué evidencia faltó al decidir.

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
| 1 | Cálculo de confianza | **Híbrida**: determinístico (`base_confidence`) + ajuste acotado del Arbiter con justificación |
| 2 | Payload del `POST /cases` | **Solo `Transaction`**; el grafo recupera el perfil |
| 3 | Notificación al dashboard | **Polling** en v1; WebSocket = mejora (entregable 10) |
| 4 | Allowlist de búsqueda web | **Tabla gobernada** con audit trail |
| 5 | Duplicados | **Idempotencia** por `transaction_id` |
| 6 | `signals` | **Tabla relacional** (unidad de evaluación) |
| 7 | `citations_*` | **JSONB** (narrativa de auditoría) |
| 8 | Perfil del cliente en el caso | **Snapshot congelado** en JSONB, sin FK |
| 9 | `Decision` | **Tabla propia** con PK compartida con `cases` |
| 10 | 🆕 HITL | **Sin `interrupt()`**: `PENDING_HUMAN` es terminal para el grafo; la resolución es flujo HTTP |
| 11 | 🆕 Riesgo vs confianza | **Dos números distintos**, con formas distintas |
| 12 | 🆕 Falla de un agente | **Degrada** la decisión, no la aborta; `FAILED` solo por excepción no capturada |
| 13 | 🆕 Errores de agente | **Tabla** `agent_errors` (el sistema los mide); la frontera expone solo `degraded_agents` |
| 14 | 🆕 Escritura del grafo | **Un solo punto**, con semántica de reemplazo del agregado |

---

## 6. Pendiente de cerrar 🔶

- **Migraciones**: postura propuesta = imagen soporta `alembic upgrade head`; el CD lo invoca como Job de pre-deploy.
- **Convención de tags** de la imagen en GHCR (semver + git SHA).
- **Zona horaria del perfil** (§2.7): se cierra en la etapa de dataset.

---

## 7. Modelo de persistencia

> Frontera **interna**: no la ve el dashboard. Se documenta porque es donde se
> resuelve el "JSONB vs relacional" y dónde viven las garantías que §2 promete.

### 7.1 Las siete tablas

| Tabla | PK | Notas |
|---|---|---|
| `transactions` | `transaction_id` (natural) | índice en `customer_id` |
| `customer_behaviors` | `customer_id` (natural) | `varchar(2)[]` y `varchar[]` para las listas |
| `cases` | `case_id` (UUID, surrogate) | FK + **UNIQUE** en `transaction_id`; índice compuesto `(status, created_at)` |
| `decisions` | `case_id` (**PK = FK** a `cases`) | 1:1 implícito, sin constraint extra |
| `signals` | `id` (BIGSERIAL) | FK a `decisions.case_id`; índice en `code` |
| **`agent_errors`** | `id` (BIGSERIAL) | 🆕 FK a `decisions.case_id`; índice en `agent` |
| `human_resolutions` | `case_id` (**PK = FK** a `cases`) | 1:1 implícito |

Los hijos llevan `ON DELETE CASCADE` a nivel BD.

**Falta**: `web_search_allowlist` (§4).

### 7.2 `agent_errors`: tabla, no JSONB

Mismo criterio que `signals`: **el sistema los mide**. *"¿Con qué frecuencia falla
el agente de inteligencia externa?"* es métrica de producción (entregable 6) y
*"¿qué decisiones se tomaron degradadas?"* es métrica de calidad (entregable 7).
Ambas quieren `GROUP BY agent`, y el índice es su razón de ser.

Columnas: `agent`, `error_type`, `message`, `occurred_at`.

`occurred_at` **no** tiene `server_default`: el instante lo acuña el grafo cuando
la falla ocurre. Con `now()` de Postgres todos los errores de un mismo commit
compartirían timestamp y se perdería justo el dato útil.

La frontera expone `degraded_agents` —solo los nombres— derivado de esta tabla con
una property del ORM. **No se modela lo que se puede derivar.**

### 7.3 Los cuatro puntos de escritura

Cada uno existe porque un observador externo necesita ver algo en ese instante.

| | Quién escribe | Qué | Por qué existe |
|---|---|---|---|
| **W0** | endpoint `POST /cases` | `transactions` + `cases` en `RECEIVED` | sin esto no hay `case_id` que devolver |
| **W1** | wrapper del background task | `status = ANALYZING` | distingue "aceptado" de "corriendo" |
| **W2** | **único nodo persistidor del grafo** | `decisions` + `signals` + `agent_errors` + `decided_at` + `status`, **una transacción** | la cola HITL |
| **W3** | endpoint `POST /resolution` | `human_resolutions` + `RESOLVED` | el grafo ya terminó |

**Garantía derivada, que el dashboard puede asumir:**

| `status` | `decision` | `human_resolution` |
|---|---|---|
| `RECEIVED`, `ANALYZING` | `null` | `null` |
| `DECIDED`, `PENDING_HUMAN` | **completa** (nunca parcial) | `null` |
| `RESOLVED` | completa | presente |
| `FAILED` | puede ser `null` | `null` |

No hay estados intermedios visibles: W2 escribe todo en un commit.

`FAILED` **no lo escribe ningún nodo**: un agente caído degrada, no aborta. Es para
una excepción no capturada del grafo entero, y la escribe el wrapper de W1 —quien
tiene el `try`—.

**Idempotencia de W2 — reemplazo del agregado.** La clave es `case_id`:

```sql
DELETE FROM decisions WHERE case_id = :id;   -- la cascada barre los hijos
INSERT INTO decisions ...; INSERT INTO signals ...; INSERT INTO agent_errors ...;
UPDATE cases SET status = ...;
```

La semántica es *"el resultado de W2 para este caso es exactamente esto"*, no
*"asegúrate de que estas filas existan"*. **Un reintento sustituye, no complementa**
— y hace falta porque `signals.id` es BIGSERIAL sin UNIQUE: una segunda escritura
no chocaría con nada y duplicaría en silencio, envenenando la unidad de medida del
entregable 7.

**Guardas en W2**, que hacen cumplir lo que §2.5 promete:

1. `decision != ESCALATE_TO_HUMAN` ⟹ `citations_internal` no vacío.
2. `decision != ESCALATE_TO_HUMAN` ⟹ `base_confidence` no es `null`.
3. `base_confidence` no `null` **y** `confidence != base_confidence` ⟹ hay `confidence_rationale`.

Las tres **levantan**, no reparan: si alguna dispara, el Arbiter tiene un bug, y
una guarda que repara lo esconde. El Arbiter degrada a `ESCALATE_TO_HUMAN` antes
de que la guarda pueda dispararse; llegar a W2 en violación es un defecto.

### 7.4 El snapshot congelado

`cases.customer_snapshot` es JSONB **nullable**, no un FK a `customer_behaviors`.

> **Congela lo mutable, referencia lo inmutable.**

Una transacción es un evento: nunca se actualiza, así que un FK siempre devuelve lo
que se usó para decidir. Un perfil de comportamiento **sí muta**: un FK haría que un
caso de enero mostrara el perfil de marzo → auditoría rota.

Corolario: **no hay FK de `transactions.customer_id` a `customer_behaviors`**. Una
transacción de un cliente sin perfil debe poder insertarse; ese caso no es un error,
es el escenario que el sistema tiene que analizar.

### 7.5 Regla JSONB vs relacional vs ARRAY

| Si el contenido… | Va a |
|---|---|
| es un escalar homogéneo, se lee siempre completo, no existe sin su dueño | **`ARRAY`** |
| tiene forma anidada, se produce y se archiva, se lee entero junto al caso | **`JSONB`** |
| tiene identidad, ciclo de vida propio, o el sistema lo **mide** | **tabla** |

Destilado: **JSONB para lo que el sistema produce y archiva; relacional para lo
que el sistema mide.** Detalle en [ADR-0002](adr/0002-jsonb-vs-relacional-vs-array.md).

### 7.6 Convenciones de persistencia

- **Enums — Opción A**: `native_enum=False`, sin CHECK a nivel BD.
- **Sin `CheckConstraint`** en general: punto ciego de `--autogenerate` y `alembic check`.
- **Nulabilidad** sale del tipo `Mapped[...]`, nunca `nullable=True/False` explícito.
- **`lazy="selectin"`** en todas las relaciones: obligatorio en async.
- **`model_dump(mode="json")`** al escribir Pydantic a JSONB.
- **PK surrogate**: UUID cuando la identidad **viaja al cliente**; entero
  autoincremental cuando es interna (y preserva orden de inserción gratis).
- **Borrado por `delete()` de Core**, no por objeto: con `lazy="selectin"` el ORM
  cargaría los hijos para borrarlos uno por uno en vez de dejar que la cascada
  de la BD haga su trabajo.
- **Mutación in situ no se detecta**: reasignar la colección completa.
- **`onupdate=func.now()`** se dispara en Python, no en la BD.
- **`now()` de Postgres es `transaction_timestamp()`**: todo lo insertado en un
  mismo commit comparte instante.

### 7.7 Cadena de migraciones

```
c558fd490ae6  (pgvector)
 → b2a8d4bf4ee2  (transactions)
   → 97de35e4842b  (customer_behaviors)
     → ac3bc6c8573d  (cases, decisions, signals, human_resolutions)
       → 307787653e5e  (scoring en decisions)
         → 694142a4c8b6  (agent_errors)  ← head
```

---

**Estado**: v0.4 — scoring y trazabilidad de ejecución cerrados y verificados
contra Postgres.
**Valida el compañero**: §1. **Valido yo**: §2–§4, §7.
