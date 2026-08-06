# Contrato de Interfaz — Sistema Multi-Agente de Detección de Fraude
**Versión 0.8 — Inteligencia externa congelada y quinto eje de auditoría**

> Define las **fronteras** entre el motor de agentes (yo), la infraestructura (mi
> compañero) y el dashboard del analista.
>
> Qué cambió respecto de versiones anteriores: [`CHANGELOG.md`](CHANGELOG.md).

---

## 0. Hay dos contratos, no uno

| | Contrato Operativo | Contrato de API |
|---|---|---|
| **Frontera con** | Infraestructura (compañero) | Dashboard |
| **Qué define** | Cómo se empaqueta, ejecuta y configura | Endpoints y schemas |
| **Punto de hand-off** | **La imagen en GHCR**, por **digest** | El API HTTP |
| **Quién valida** | Compañero | Yo |

---

## 1. Contrato Operativo (frontera con infraestructura)

### 1.1 Reparto CI / CD

| Etapa | Responsable | Contenido |
|---|---|---|
| **CI** — build | **Yo** | Dockerfile, GitHub Actions, lint + tests, publicar imagen en **GHCR** |
| **CD** — deploy | **Compañero** | Terraform, orquestador, invocar migraciones, rollout, ConfigMaps/Secrets |

La costura no es el código ni los schemas: **es la imagen versionada en GHCR**.

### 1.2 Ejecución: una imagen, cuatro modos de arranque

```
# Modo servir (proceso principal)
uvicorn app.main:app --host 0.0.0.0 --port ${APP_PORT}

# Modo migrar (Job de PRE-deploy, con el digest que se va a desplegar,
# en UNA sola instancia; si falla, ABORTA el rollout)
alembic upgrade head

# Modo sembrar (Job de POST-deploy, idempotente, sin --reset;
# si falla, NO aborta el rollout)
python scripts/seed.py

# Modo fetch-intel (Job periódico, idempotente;
# si falla, NO aborta el rollout)
python scripts/fetch_threat_intel.py
```

> **No** va `alembic upgrade head` en el entrypoint normal: con N réplicas tendrías
> N migraciones concurrentes → race conditions y locks.
> ([ADR-0009](adr/0009-migraciones-como-job-de-pre-deploy.md))

**La asimetría entre los dos Jobs es deliberada.** La migración es obligatoria
para que la aplicación arranque, así que su falla aborta el rollout. El seed carga
datos y el sistema funciona sin ellos: un seed fallido deja un dashboard vacío, no
un servicio roto ([ADR-0010](adr/0010-seed-como-job-de-post-deploy.md)).

> ⚠️ `seed.py --reset` ejecuta `TRUNCATE ... CASCADE` y **arrastra casos,
> decisiones y resoluciones humanas** —la evidencia del entregable 8—. Es
> herramienta de desarrollo local y de runbook: **no aparece en ningún pipeline**,
> y el propio script lo rechaza salvo con `ENVIRONMENT=local`.

El seed **también construye el índice vectorial** de políticas. Sin
`GEMINI_API_KEY` lo omite con aviso en vez de fallar: el resultado es un estado
previsto y medido —*chunks pendientes de indexar*, §3.3—, no una caída.

**`fetch-intel` es la misma asimetría que el seed, y por el mismo motivo**
([ADR-0014](adr/0014-la-inteligencia-externa-se-recoge-en-build-y-se-consulta-congelada.md)).
El grafo no sale a la red: en runtime, el nodo Threat Intel hace *lookup* sobre
lo que este Job ya congeló en `threat_indicators`. Un fetch fallido deja un
snapshot viejo —estado previsto y medido, §3.3—, nunca un servicio roto.

**El allowlist vacío falla ruidosamente**, a propósito distinto del anterior:
sin esa guarda, el Job pagaría una búsqueda por emisor y guardaría cero filas,
que se lee exactamente igual que "no hay alertas" — el peor de los dos
fallos posibles, porque no avisa.

#### Expand / contract

Regla sobre **cómo se escriben** las migraciones, no sobre dónde corren:

- Toda columna nueva nace **nullable**.
- Retirar algo cuesta **dos releases**: primero dejar de escribirlo, después
  quitarlo.
- **Nunca un `DROP COLUMN` en la misma release que deja de usar la columna.**

El motivo es el rollout: durante unos minutos conviven la versión vieja y la
nueva contra el mismo esquema. Una migración que rompe hacia atrás rompe a las
réplicas que todavía no se reemplazaron.

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
| `DATABASE_URL` | `postgresql+psycopg://user:pass@host:5432/fraud?sslmode=require` |
| `ANTHROPIC_API_KEY` | `sk-ant-...` |
| `GEMINI_API_KEY` | `...` |
| `LANGSMITH_API_KEY` | `ls-...` |
| `LANGSMITH_TRACING` | `true` |
| `LANGSMITH_PROJECT` | `fraud-detection` |
| `LOG_LEVEL` | `INFO` |
| **`ENVIRONMENT`** | `local` \| `staging` \| `production` 🆕 |

> `LOG_LEVEL` gobierna también el echo de SQL de SQLAlchemy: solo en `DEBUG`.
>
> **`ENVIRONMENT` hay que inyectarla en todos los ambientes**, incluidos los Jobs
> de migración y de seed. Habilita el guard de `seed.py --reset`, que solo permite
> la operación destructiva con `local`: la variable **ausente rechaza**, que es el
> default seguro. Si falta, la aplicación funciona igual.
>
> `ANTHROPIC_API_KEY` y `GEMINI_API_KEY` son las **únicas** variables de los
> proveedores. El modelo, la dimensión y las plantillas de prompt viven en código:
> configurables por `env` podrían cambiarse sin que suban las versiones selladas
> en `decisions`, y los cinco sellos de §2.5 mentirían a la vez.
> El allowlist de búsqueda web **no** es env var → tabla gobernada (§4).
>
> 🆕 `ANTHROPIC_API_KEY` alimenta ahora **dos** puertos: `Narrator` (explicación
> al cliente) y `Searcher` (inteligencia externa, consumido por el Job
> `fetch-intel`, nunca por el grafo). Misma regla: sólo la clave es variable de
> entorno; el modelo y la plantilla de búsqueda viven en código.
>
> 🆕 **Techo organizacional de dominios.** El proveedor de búsqueda admite
> restringir por dominio a nivel de la organización, en su consola —fuera de
> este repo—. Esa lista sólo puede **acotar**, nunca **expandir**, lo que
> `allowed_domains` pide por request: es un segundo filtro invisible desde el
> código, que puede vaciar los resultados sin que nada falle. Infraestructura
> tiene que saber que existe antes de depurar un fetch que vuelve vacío.

#### Tres entornos, no uno

| Entorno | Dónde | Para qué | Quién la toca |
|---|---|---|---|
| **Local** | contenedor de `compose.yml` | iterar migraciones, smoke tests | cada uno la suya |
| **Compartido** | RDS, base `fraud` | integración: el motor y el dashboard | los dos |
| **Producción** | no existe todavía | el despliegue final | el CD |

El local no desaparece al existir el compartido: se **itera** en local, se
**integra** en compartido.

Dos precisiones que salieron de crear la compartida:

- La base es **`fraud`**, no la que RDS provisiona por defecto (`postgres`). Esa
  queda como base de mantenimiento; mezclarla con datos de aplicación estorba en
  restores y permisos.
- Las extensiones son **por base de datos**, no por cluster: `CREATE EXTENSION
  vector` corre dentro de `fraud`.

#### Forma de `DATABASE_URL`

**`?sslmode=require` es obligatorio.** RDS trae `rds.force_ssl` activo: una
conexión sin TLS se rechaza en el handshake, antes de autenticar.

**El password viaja percent-encoded.** No es cosmético: dentro de una URL el
password no es un campo sino un tramo delimitado por `:` y `@`, así que cualquier
carácter estructural lo parte. Un `$` pegado al `@` se lo come Bash como expansión
de parámetros al hacer `source` —sin error ni advertencia—: password mutilado y un
`authentication failed` que parece problema de AWS. SQLAlchemy hace `unquote` al
parsear, así que el driver recibe el literal: es el mecanismo previsto, no un
parche.

El `%` del encoding no rompe Alembic porque `env.py` inyecta la URL desde
`settings` con `create_engine` directo, sin pasar por el `ConfigParser` de
`alembic.ini`. Aquella decisión paga aquí.

#### Versión de Postgres

**18** es la versión destino, en los tres entornos. Mientras difieran, "pasa en
local" deja de ser evidencia de "pasa en la nube". La versión menor puede diferir
(18.1 local vs 18.3 en RDS): mismo formato en disco, mismo SQL. pgvector 0.8.1.

### 1.5 Empaquetado

- Build reproducible: `uv sync --frozen`.
- Plataforma `linux/amd64`. Usuario no-root. `.dockerignore` excluyendo `.git`, `.venv`, `.env`.

#### El artefacto de hand-off es el **digest**

El CD despliega por digest, no por tag ([ADR-0008](adr/0008-el-artefacto-de-hand-off-es-el-digest.md)).
Un tag es una etiqueta **mutable**: se puede reapuntar, así que "desplegar el tag
`1.2.0`" no garantiza qué bytes corren. El digest es el contenido.

| Evento | Qué produce | Qué usa el CD |
|---|---|---|
| push a `main` | imagen + tags legibles (`sha-abc1234`, semver) | — |
| release | tag semver adicional | — |
| deploy | — | **`ghcr.io/…@sha256:…`** |

Los tags siguen existiendo porque un humano necesita leer qué es cada imagen.
**Nunca `latest`** para CD.

**El tag de git es la fuente de verdad de la versión.** `pyproject.toml` deja de
ser autoridad sobre el número: uno solo puede quedar desactualizado, y el que se
puede firmar es el de git.

#### Acceso a GHCR

El paquete queda **privado**; el CD se autentica con un token con
`read:packages`. Se escribe porque GHCR es privado por defecto y el `docker pull`
falla con un error de autenticación que se lee como *"la imagen no existe"*.

### 1.6 Pipeline de CI

```
lint → pytest → check_policies → export_data_model_diagram --check
     → alembic upgrade head → alembic check → build → push a GHCR
```

| Gate | Qué detecta | ¿Necesita servicios? |
|---|---|---|
| `pytest` | regresión de lógica | no |
| `check_policies.py` | el motor deja de reproducir el ground truth (7 000 filas) | no |
| `export_data_model_diagram.py --check` | modelo cambiado **sin diagrama** | no |
| `alembic check` | modelo cambiado **sin migración** | Postgres |

> `alembic check` exige que la base esté en `head`, por eso el `upgrade` va antes.
> Requiere Postgres como `services:` en el job.
>
> Los dos gates del medio no necesitan red ni base: cubren los dos desfases
> posibles del modelo —sin migración y sin diagrama— y corren en segundos.
>
> **`check_retrieval.py` no entra**: mide la recuperación semántica y necesita el
> índice vectorial poblado más los embeddings de las queries, cuyo caché vive en
> el proceso. Corre contra una base sembrada, no en el job de PR.

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

#### Precedencia de `DecisionType`

Una transacción puede satisfacer **dos políticas a la vez** con acciones
distintas —14 lo hacen en el dataset, `FP-02;FP-05` es la combinación más
común—. Cuando eso pasa, gana la más restrictiva:

BLOCK > ESCALATE_TO_HUMAN > CHALLENGE > APPROVE

Es una regla del **contrato**, no del Arbiter: el harness del entregable 7 la usa
para construir la decisión esperada, y si el Arbiter usara otra, la comparación
mediría la discrepancia de reglas en vez de la calidad del sistema.

### 2.3 Endpoints

| Método | Ruta | Propósito | Body | Respuesta | Código |
|---|---|---|---|---|---|
| `POST` | `/api/v1/cases` | Ingresar transacción | `Transaction` | `CaseCreated` | `202` nuevo / `200` reintento |
| `GET` | `/api/v1/cases` | Listar/filtrar cola (HITL) | query: `status`, `limit`, `offset` | `Page[CaseSummary]` | `200` |
| `GET` | `/api/v1/cases/{case_id}` | Detalle completo | — | `CaseDetail` | `200` |
| `POST` | `/api/v1/cases/{case_id}/resolution` | Acción del analista | `HumanResolutionIn` | `CaseDetail` | `200` |
| `GET` | `/api/v1/policies` | 🆕 Catálogo con estado de cada política | — | `list[PolicyRead]` | `200` |
| `POST` | `/api/v1/policies` | 🆕 Alta de política (norma + vinculación opcional) | `PolicyIn` | `PolicyRead` | `201` |
| `GET` | `/api/v1/predicates` | 🆕 La biblioteca, para el compositor del dashboard | — | `list[PredicateSpec]` | `200` |
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
| **`issuer_bank`** | `str \| null` | 🆕 código del banco emisor, **normalizado a mayúsculas**; insumo de FP-10 (alerta externa). Nullable: no todo emisor del dataset está en el corpus de amenazas |

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
| **`usual_channel`** | `Channel` | 🆕 singular, no lista |
| **`account_creation_date`** | `date` | 🆕 |
| **`last_profile_update`** | `datetime` | 🆕 aware, UTC |
| **`daily_limit`** | `Decimal` | 🆕 `> 0`, misma moneda |
| **`currency`** | `str` | 🆕 ISO 4217, mayúsculas |
| **`timezone`** | `str` | 🆕 IANA; se **rechaza** lo que `ZoneInfo` no resuelva |
| **`segment`** | `Segment` | 🆕 `retail`, `premium`, `business` |

> **La moneda es atributo de la cuenta**, no del país donde ocurre la compra: una
> tarjeta liquida en la moneda de su cuenta. Es lo que hace comparable `amount`
> con `usual_amount_avg`; sin ella, "3× el promedio" mezcla unidades y fabrica
> falsos positivos. La dimensión internacional sobrevive intacta porque `country`
> sigue variando. *Fuera de alcance, documentado: cuentas multi-moneda y FX.*
>
> **`usual_channel` es singular a propósito.** `Channel` tiene dos valores, así
> que una lista tendría un elemento —idéntico al singular— o los dos, y entonces
> FP-06 ("canal nuevo con monto alto") nunca podría dispararse. Se revisa el día
> que `Channel` crezca (ATM, POS, API).
>
> **`segment` es enum y no texto libre** porque la aplicación **agrupa por él**:
> FP-08 compara contra el promedio del segmento. Un `varchar` admitiría `Retail`
> y `retail` como grupos distintos y partiría el promedio sin que nada falle.

> **Semántica del rango horario**: `[start, end]` **inclusive**, en **hora local
> del cliente** — la que define `timezone`, nunca UTC ni un supuesto global.
> `"08-20"` incluye las 20:45. Un cliente nocturno (`22-06`) es válido:
> `start > end` **no** está prohibido, y la lógica de comparación debe contemplar
> el cruce de medianoche.
>
> Evaluar la ventana en UTC clasificaría mal un tercio de las transacciones del
> dataset. No es un detalle de precisión: es evaluar otra franja horaria.
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
| **`matched_policies`** | `list[str]` | 🆕 políticas que dispararon **completas**. El vocabulario del ground truth |
| **`policy_catalog_version`** | `str \| null` | qué versión del catálogo se evaluó (ej. `2025.1-b1`) |
| **`retrieval_index_version`** | `str \| null` | 🆕 con qué generación del índice se recuperó (`gemini-embedding-2:1536:doc:1`). `null` = **no hubo recuperación** |
| **`explanation_prompt_version`** | `str \| null` | 🆕 con qué modelo y prompt se redactó `explanation_customer`. `null` = **ningún modelo participó** |
| **`threat_intel_version`** | `str \| null` | 🆕 quinto eje: con qué generación del snapshot externo se consultó (`claude-sonnet-4-6:issuer-alert:v1`). `null` = **no se consultó snapshot** — nunca "no había alertas": un corpus vacío consultado igual sella versión |
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

Formalmente, cuando `decision != ESCALATE_TO_HUMAN`: `citations_internal`
contiene una cita por **cada** `policy_id` de `matched_policies`, **y**
`base_confidence` no es `null`.

**Contención, no "lista no vacía".** La formulación anterior fallaba por los dos
lados. Era **débil**: una lista con las citas equivocadas la satisface, así que el
sistema podía bloquear citando normas que no aplicó. Y era **insatisfacible para
`APPROVE`**: el catálogo rechaza al cargar cualquier vinculación con
`action: APPROVE`, así que ninguna cita puede respaldar una aprobación —y el 90%
del tráfico no dispara ninguna política—.

**La obligación nace de la evidencia, no del veredicto.** Si alguna política
disparó, tiene que estar citada; si no disparó ninguna, no hay nada que exigir y
la condición se cumple vacíamente. Por eso `APPROVE` no necesita exención.

**Contiene, no iguala**: la búsqueda por similitud agrega políticas relacionadas
que no dispararon, y eso es aporte al Arbiter, no violación.

`ESCALATE_TO_HUMAN` queda exento: la ausencia de respaldo *es* la razón para
llamar al humano.

> **Cómo se cumple.** La citación se resuelve **por identidad** —lookup por
> `policy_id` contra el catálogo— y no por búsqueda vectorial
> ([ADR-0011](adr/0011-citacion-por-identidad-descubrimiento-por-similitud.md)).
> Ese camino no consulta el índice ni la red, así que tiene recall 1.0 por
> construcción y sobrevive a que el proveedor de embeddings se caiga.

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
  cliente**; la zona sale de `CustomerBehavior.timezone`, no de un supuesto
  global. ✅ *Cerrado en la etapa de dataset: el supuesto `America/Lima` de v0.2
  está muerto.*

  El dataset tiene siete países y afecta al 86% de los clientes. Derivar la zona
  del país en tiempo de lectura tampoco sirve: US abarca varias zonas y MX
  también. Se descartó guardar la ventana ya convertida a UTC —el horario de
  verano hace que la conversión no sea constante y hornearía un supuesto de
  estación—.

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

### 3.3 Vista de políticas 🆕

**Lista**: cada política con su estado —`activa`, `excluida`, `pendiente de
vinculación`, `vinculación obsoleta`— desde `GET /api/v1/policies`.

**Alta**: formulario en dos secciones.

| Sección | Campos | Obligatoria |
|---|---|---|
| Norma | `policy_id`, `version`, texto | sí |
| Vinculación | `action` + predicados compuestos desde `GET /api/v1/predicates` | **no** |

Dejar la vinculación vacía es un **uso previsto, no un error**: publica la norma
hoy —el RAG la cita desde ese momento— y la ejecuta cuando alguien la componga.

> Los estados salen de comparar documentos contra vinculaciones y de verificar
> la huella del texto. *Pendientes* y *obsoletas* son dos de las tres métricas
> operativas del entregable 6.

**Tercera métrica: chunks pendientes de indexar.** Un documento publicado y no
indexado es **citable por identidad e invisible por similitud**: si dispara, se
cita igual —esa vía no consulta el índice—; si no dispara, no hay forma de que
aparezca. Estado legítimo y **silencioso**: nada falla.

**Cuarta métrica 🆕: antigüedad del snapshot de inteligencia externa vigente**
—`now() - max(retrieved_at)` sobre `threat_indicators` en la generación activa.
Un snapshot viejo es **citable y silenciosamente obsoleto**: el mismo estado
legítimo que motivó la primera métrica, del otro lado del puerto
([ADR-0014](adr/0014-la-inteligencia-externa-se-recoge-en-build-y-se-consulta-congelada.md)).
Nada en el sistema falla si el Job `fetch-intel` deja de correr; esta métrica es
lo único que lo haría visible.

Las cuatro son la misma clase de cosa —desincronizaciones entre artefactos con
dueños distintos—. La norma sin vinculación no se evalúa; la norma sin chunk no
se descubre; la huella rota deja de evaluarse sin dejar de citarse; el snapshot
viejo se sigue consultando sin avisar que está viejo.

---

## 4. Búsqueda web gobernada — allowlist como tabla

El allowlist es **dato de gobernanza** (mutable, administrado por un humano con
auditoría), no config de infraestructura. Vive en Postgres, no en env var.

**Tabla `web_search_allowlist`**: `domain`, `added_by`, `added_at`, `active`, `reason`.

- Se **siembra** con el seed; se administra como `merchant_blacklist`.
- **🆕 Gobierna el camino de escritura, no el de lectura**
  ([ADR-0014](adr/0014-la-inteligencia-externa-se-recoge-en-build-y-se-consulta-congelada.md)).
  v0.2–v0.7 la describían filtrando el *fetch* en runtime; con el snapshot
  congelado el enforcement ocurre **una vez, en el Job `fetch-intel`**: lo que
  no pasa la lista no llega a `threat_indicators`, y en runtime el grafo no
  tiene nada que filtrar —hace *lookup*, nunca búsqueda—.
- **🆕 Sin caché.** A diferencia de `merchant_blacklist`, la lee un Job de build
  una vez por corrida, no el grafo una vez por transacción: no hay lectura
  repetida en runtime que justifique TTL ni invalidación (§4.2).
- Lo rechazado por el *enforcement* se registra en el **informe del Job**, no en
  una tabla del grafo: en runtime no hay nada que descartar, porque nada
  indebido entró.

**Regla general reutilizable**: *¿es config de infraestructura (estática, por deploy)
o dato de gobernanza (mutable, con audit trail)?* Lo primero → env var. Lo segundo → tabla.

### 4.1 Las políticas también son dato de gobernanza 🆕

Por la misma regla, y es el caso más claro de los tres. Se modelan como **dos
tablas con dueños y ciclos de vida distintos** ([ADR-0007](adr/0007-la-forma-ejecutable-de-una-politica-es-una-vinculacion.md)):

| Tabla | Dueño del dato | Contenido |
|---|---|---|
| `fraud_policies` | el banco | `policy_id`, `version`, `text` — lo que indexa el RAG |
| `policy_bindings` | nosotros | `condition`, `action`, `excluded_reason`, `source_fingerprint`, `bound_by`, `bound_at` |

El documento no se edita: la traducción vive aparte y declara de qué texto se
derivó. Si el banco cambia la redacción, la huella deja de coincidir y la
política **se degrada** —deja de evaluarse, sigue citable—. El sistema no puede
aplicar un umbral distinto del que cita.

> Entran con su consumidor, el RAG. Hasta entonces el catálogo vive en archivos
> versionados bajo `data/policies/`.

### 4.2 Cachear con TTL, no solo con invalidación 🆕

La versión anterior decía *"se cachea en memoria con invalidación al escribir"*,
y eso asume **un proceso**. Con N réplicas, invalidar limpia la que recibió la
escritura; las demás siguen sirviendo la lista vieja sin que nada falle.

Postura: **TTL de 60 s más `invalidate()`**. El TTL da obsolescencia acotada en
todas las réplicas sin coordinación; el `invalidate()` se conserva para que la
réplica que atiende un alta desde el dashboard la vea al instante.

Aplica a las cachés que el **grafo** lee por transacción: `merchant_blacklist` y
**🆕 `threat_indicators`** (el índice `(tipo, valor) → observaciones` que arma
el Threat Intel Agent). **No** aplica a `web_search_allowlist`: esa la lee el
Job `fetch-intel` una vez por corrida de build, no el grafo (§4).

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
| 15 | 🆕 Forma ejecutable de una política | **Vinculación** al documento normativo, con huella. El documento es del banco |
| 16 | 🆕 `NO_CUSTOMER_PROFILE` en el riesgo | **No suma**. "No pude comparar" no es "esto es sospechoso" |
| 17 | 🆕 Caché de datos de gobernanza | **TTL + invalidación**, no solo invalidación (§4.2) |
| 18 | 🆕 Búsqueda de inteligencia externa | **Se recoge en build, se consulta congelada** — nunca en vivo dentro del grafo (ADR-0014) |
| 19 | 🆕 Evidencia externa en el veredicto | **Entra por política del catálogo** (FP-10 vinculada), no por señal con código propio fuera de su vocabulario (ADR-0015) |


---

## 6. Pendiente de cerrar

*(nada)*

Las dos viñetas que llevaban abiertas desde v0.2 quedaron cerradas y
documentadas:

| Pendiente | Resolución |
|---|---|
| Convención de tags | [ADR-0008](adr/0008-el-artefacto-de-hand-off-es-el-digest.md): el hand-off es el **digest**; los tags son etiquetas legibles |
| Migraciones | [ADR-0009](adr/0009-migraciones-como-job-de-pre-deploy.md): Job de pre-deploy, mismo digest, una instancia, compatible hacia atrás |

**§6 queda vacío por primera vez desde v0.2.**

---

## 7. Modelo de persistencia

> Frontera **interna**: no la ve el dashboard. Se documenta porque es donde se
> resuelve el "JSONB vs relacional" y dónde viven las garantías que §2 promete.

### 7.1 Las catorce tablas

| Tabla | PK | Notas |
|---|---|---|
| `transactions` | `transaction_id` (natural) | índices compuestos `(customer_id, timestamp)` y `(device_id, timestamp)` |
| `customer_behaviors` | `customer_id` (natural) | `varchar(2)[]` y `varchar[]` para las listas |
| `cases` | `case_id` (UUID, surrogate) | FK + **UNIQUE** en `transaction_id`; índice compuesto `(status, created_at)` |
| `decisions` | `case_id` (**PK = FK** a `cases`) | `matched_policies varchar[]` y `policy_catalog_version` 🆕 —`ARRAY` por la regla de §7.2: escalares homogéneos, se leen completos, no existen sin su dueño—. 1:1 implícito, sin constraint extra |
| `signals` | `id` (BIGSERIAL) | FK a `decisions.case_id`; índice en `code` |
| **`agent_errors`** | `id` (BIGSERIAL) | 🆕 FK a `decisions.case_id`; índice en `agent` |
| `human_resolutions` | `case_id` (**PK = FK** a `cases`) | 1:1 implícito |
| `merchant_blacklist` | `merchant_id` (natural) | gobernanza; baja lógica con `active` |
| **`fraud_policies`** | `(policy_id, version)` compuesta | 🆕 documento normativo; append-only por versión. **Sin `active`**: el estado se deriva |
| **`binding_sets`** | `version` (`2025.1-b1`) | 🆕 encabezado del set de vinculaciones; a lo sumo uno activo, por **índice parcial único** |
| **`policy_bindings`** | `(binding_set_version, policy_id)` | 🆕 FK **compuesta** a `fraud_policies(policy_id, version)`; `condition` JSONB nullable |
| **`policy_chunks`** | `(index_version, chunk_id)` | 🆕 `embedding vector(1536)`; **ningún índice extra**: la PK ya sirve el filtro por generación |
| **`threat_indicators`** | `id` (BIGSERIAL) | 🆕 gobernanza; UNIQUE `(indicator_type, value, observed_at, snapshot_version)` — hace idempotente el fetch; **sin índice de lectura**: decenas de filas, se cachean (§4.2) |
| **`web_search_allowlist`** | `domain` (natural) | 🆕 gobernanza; baja lógica con `active`, igual forma que `merchant_blacklist` (§4) |

Los hijos llevan `ON DELETE CASCADE` a nivel BD.

> **Por qué `fraud_policies` no lleva `active`.** El patrón de
> `merchant_blacklist` invita a copiarla, pero ahí la bandera **es** el dato. En
> el catálogo los cuatro estados son **derivados** (ADR-0007: derivar, nunca
> escribir), y una columna `active` sería una segunda fuente de verdad sobre
> *¿esta política aplica?*. El retiro ya es expresable:
> `policy_bindings.active = false`, o no publicar vinculación para la versión
> nueva.
>
> **La FK compuesta de `policy_bindings`** convierte en **estructura** una
> validación que era código: una vinculación no puede apuntar a un documento
> inexistente porque la base no la deja entrar.
>
> **`policy_chunks` acumula generaciones**: no hay poda. Por eso
> `WHERE index_version = <vigente>` no es un filtro sino un **invariante de
> corrección** —sin él la búsqueda mezcla generaciones y devuelve vecinos de otro
> modelo, sin fallar— ([ADR-0012](adr/0012-el-indice-vectorial-es-dato-derivado-y-versionado.md)).
>
> 🆕 **`threat_indicators` tiene el mismo invariante**, con `snapshot_version` en
> vez de `index_version`: sin el filtro, un veredicto podría consultar dos
> generaciones a la vez y `threat_intel_version` sellaría una sola
> ([ADR-0014](adr/0014-la-inteligencia-externa-se-recoge-en-build-y-se-consulta-congelada.md)).
> `observed_at` (publicación) ≠ `retrieved_at` (recuperación) — FP-10 evalúa la
> primera, y evaluar la segunda haría que un fetch de hoy volviera reciente una
> alerta de hace un año.

> `merchant_blacklist` es la primera tabla de **gobernanza** —dato mutable,
> administrado por un humano, con audit trail—, la categoría que §4 definió para
> el allowlist. Comparte su forma a propósito, incluido el nombre en singular:
> describe la lista, no sus filas.
>
> PK natural con bandera `active`, no surrogate con historial de altas y bajas.
> La consulta real es un lookup puntual, y la historia no se pierde: el caso
> **congela su propia evidencia** en `signals`. Si el comercio se retira en marzo,
> el caso de enero sigue diciendo qué decidió y por qué —mismo principio que
> `cases.customer_snapshot`—.

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

1. `decision != ESCALATE_TO_HUMAN` ⟹ `citations_internal` **contiene una cita por cada** `policy_id` de `matched_policies`.
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

### 7.7 El invariante *as-of*

**Toda consulta de historial lleva `timestamp <= :as_of`**, donde `as_of` es el
timestamp de la transacción bajo análisis — **nunca `now()`**.

Una transacción se juzga con lo que existía en el instante en que ocurrió. El
`<=` es inclusivo a propósito: la transacción cuenta para su propia ventana, que
es lo que FP-03 necesita ("más de 3 en menos de 5 minutos, contando ésta").

Por qué es fácil de pasar por alto: **en producción es imposible de violar**. El
futuro no está en la tabla cuando llega el caso. En evaluación sí, porque el
dataset se carga completo de una vez. Un agente que no filtre **funciona bien en
producción y solo falla en evaluación** — y falla hacia arriba, viendo ráfagas
completas desde su primera transacción e inflando su propio recall. El harness
certificaría un sistema que no funciona.

**Se hace cumplir en un solo punto**: `db/repositories/transaction_history.py`.
Un invariante que depende de que cada autor lo recuerde no es un invariante.

Dos funciones, dos ejes de acceso:

| Eje | Políticas | Por qué |
|---|---|---|
| cliente | FP-04, FP-05, FP-11 | reconstruyen la actividad de la cuenta |
| dispositivo | FP-03 | un dispositivo usado con varias cuentas **es** la señal |

FP-03 no filtra por cliente: hacerlo escondería el caso que la política busca. De
ahí que sean dos índices y no uno.

El ground truth del dataset respeta el mismo invariante: en una ráfaga de cuatro,
solo la que **cierra** el patrón lleva la etiqueta. Cuando llegó la primera, el
patrón todavía no existía y aprobarla era la respuesta correcta.

### 7.8 Cadena de migraciones

```
c558fd490ae6  (pgvector)
 → b2a8d4bf4ee2  (transactions)
   → 97de35e4842b  (customer_behaviors)
     → ac3bc6c8573d  (cases, decisions, signals, human_resolutions)
       → 307787653e5e  (scoring en decisions)
         → 694142a4c8b6  (agent_errors)
           → 073738cbc0ec  (campos de evaluación en customer_behaviors)
             → 699755dfc00e  (índices de historial)
               → 1276e208c3d9  (merchant_blacklist)
                 → 8990ef73796f  (matched_policies, policy_catalog_version)
                   → ec429a4e2aa1  (catálogo de políticas: 4 tablas)
                     → 8db41fe7465f  (sello del prompt de explicación)
                       → 3367ac570a62  (threat_indicators)
                         → 5730aa53f76d  (web_search_allowlist, issuer_bank)
                           → f193c092654b  (sello del snapshot externo)  ← head
```

---

**Estado**: v0.8 — inteligencia externa congelada y sin decisiones conjuntas
pendientes. El motor reproduce el ground truth en las 7 000 transacciones, en
memoria y contra Postgres; los casos llegan a `DECIDED` con respaldo interno
verificable, y cada decisión sella los **cinco** ejes de auditoría. FP-10 pasa
de excluida a vinculada: activa, citable y sin ground truth reproducible —el
harness la reporta así, nunca como recall 0—.

**§1 validado por el compañero.** ADR-0008 a ADR-0010 siguen **aceptados**.
**Valido yo**: §2–§4, §7.
