# Repaso — Etapa "Fundación de base de datos"
**Sistema Multi-Agente de Detección de Fraude · handoff de continuidad**

> Documento de cierre de etapa. Destila todo lo decidido y construido hasta la
> fundación de datos, para retomar en el chat dedicado a `domain-models` con el
> contexto ya condensado.

---

## 1. Contexto y objetivo

Adaptación del reto original (sistema multi-agente de detección de fraude en
transacciones financieras) al proyecto final del programa de IA Generativa, apuntando
a la columna "Excelente (4)" de la rúbrica en los entregables 2–10. El sistema analiza
transacciones con señales ambiguas, consulta políticas internas por RAG, busca
inteligencia externa (web gobernada), orquesta agentes para decidir de forma trazable, e
incluye revisión humana (HITL).

Reparto: **yo** desarrollo el sistema de agentes y dominio; **mi compañero**, la
infraestructura (Docker, CI/CD, nube). Se trabaja por separado y se acopla después.

---

## 2. Decisiones de arquitectura macro

- **Interno síncrono, sin broker.** Un solo servicio desplegable (monolito en-proceso).
  Se descartó Kafka/event-driven: el HITL asíncrono lo resuelve el *checkpointer* de
  LangGraph, no un broker.
- **Asíncrono en el borde.** El cliente (dashboard) no bloquea 15–30s: `POST` devuelve
  `202` + `case_id`, el análisis corre en segundo plano, el dashboard consulta estado
  (patrón caso + estado). *Async-en-el-borde ≠ event-driven* (ejes distintos).
- **Usuario = analista de fraude con dashboard.** Notificación por **polling** en v1;
  WebSocket queda como mejora (entregable 10).
- **Event-driven diferido** a la sección de Recomendaciones (entregable 10): se describe
  la evolución a escala sin cargar el riesgo de entrega.

---

## 3. Los dos contratos

Existen **dos fronteras**, no una:

- **Contrato Operativo** (con infra / compañero): cómo se empaqueta, ejecuta y configura
  el servicio. Punto de hand-off = **la imagen en GHCR**. Puerto, `/health`, `/ready`,
  env vars, comando de arranque.
- **Contrato de API** (con el dashboard): endpoints y schemas. `status` (etapa del
  pipeline) ≠ `decision` (veredicto). `case_id` (UUID del servidor) ≠ `transaction_id`.

Detalle completo en `contrato_de_interfaz_v0.2.md`.

---

## 4. Reparto y fronteras con infraestructura

- **CI (mío):** Dockerfile, GitHub Actions, lint + tests, publicar imagen en GHCR.
- **CD (compañero):** orquestador/nube (a su criterio), Terraform, rollout, secretos.
- **Hand-off:** imagen versionada en GHCR con **tags inmutables** (semver + git SHA, nunca `latest`).
- **Migraciones:** la imagen soporta dos modos de arranque (servir `uvicorn` / migrar
  `alembic upgrade head`). El CD invoca la migración como **Job de pre-deploy**, no en el
  entrypoint normal (evita migraciones concurrentes entre réplicas). *(🔶 confirmar en reunión.)*
- **Plataforma destino** (amd64 vs arm64): depende de los runners/nodos del compañero. Local confirmado `x86_64`. *(🔶)*

---

## 5. Stack y justificaciones

| Herramienta | Rol | Por qué |
|---|---|---|
| **uv** (`--package`) | gestor de proyecto | build reproducible (`uv.lock`); app empaquetable (el Dockerfile de 2 etapas instala el proyecto) |
| **SQLAlchemy 2.0 (async) + ORM** | ORM / persistencia | el dominio son entidades con ciclo de vida (unit of work); **no SQLModel** (no fusionar capa API y BD) |
| **psycopg3** (`psycopg[binary]`) | driver Postgres | sync y async con la **misma URL** (app async / Alembic sync) |
| **Alembic** (sync) | migraciones | versionadas; sync evita el loop async → sin footgun de Windows en migraciones |
| **pydantic-settings** | config | lee env vars / `.env`, precedencia 12-factor |
| **FastAPI + uvicorn** | API | entregable 5 |
| **LangGraph / LangChain / LangSmith** | grafo de agentes / observabilidad | el bosquejo ES un `StateGraph`; LangSmith cubre monitoreo (6) y evals (7) |
| **Postgres + pgvector** | BD relacional **y** vectorial | una sola BD: transacciones + audit + cola HITL + vectores + checkpointer → mínimo acople |

---

## 6. La tubería construida (estado actual)

1. **docker-compose** con `pgvector/pgvector:pg17` + `healthcheck` (`pg_isready`). Volumen
   nombrado `pgdata`. Config por `${VAR:-default}`.
2. **Config** (`config/settings.py`): `BaseSettings` con `database_url`, `extra="ignore"`,
   instancia única `settings`.
3. **Engine async** (`db/session.py`): `create_async_engine` (psycopg3),
   **`expire_on_commit=False`** (crítico en async), `pool_pre_ping=True`, `get_session`
   como dependencia. `Base` (`DeclarativeBase`) en `db/base.py`.
4. **Alembic**: `env.py` cableado para leer `DATABASE_URL` desde `settings` (vía
   `create_engine` directo, sin pasar por `alembic.ini` → evita el footgun de `%` en
   ConfigParser). Primera migración habilita **pgvector** (`CREATE EXTENSION IF NOT EXISTS
   vector`, idempotente).
5. **Entidad `Transaction`** modelada de punta a punta: schema Pydantic (`TransactionIn`),
   modelo ORM (`Transaction`), migración autogenerada, tabla verificada en Postgres.

**Estado del grafo Alembic:** `c558fd490ae6` (pgvector) → `b2a8d4bf4ee2` (transactions, head).

---

## 7. Convenciones fijadas

- **Git / GitHub Flow:** `feature/*` → PR → `main` (estable, releasable). **Squash and
  merge** (1 PR = 1 entrada). Ramas cortas por unidad de trabajo. `main` es default en GitHub.
- **Commits:** Conventional Commits (`feat(db): ...`, `chore: ...`).
- **Naming:** distribución con guiones (`multiagent-fraud-detection`), import con guiones
  bajos (`multiagent_fraud_detection`). ORM = nombre limpio de la entidad (`Transaction`);
  Pydantic = sufijo de rol (`...In`, `...Read`).
- **PK:** natural cuando hay id externo estable (`transaction_id`, `customer_id`);
  surrogate (UUID) cuando la identidad la acuña el servidor (`case_id`).
- **Enums:** **Opción A — sin CHECK a nivel BD** (`native_enum=False`, `create_constraint`
  por defecto en `False`). Validación en boundary Pydantic + in-Python de SQLAlchemy.
  Aplica a todos los enums (`Channel`, `CaseStatus`, `DecisionType`, `HumanAction`, `Severity`).
- **Tipos:** dinero → `Numeric(12,2)` / `Decimal` (nunca float). Fechas → `AwareDatetime`
  (Pydantic) / `TIMESTAMPTZ` (`DateTime(timezone=True)`), en UTC; horas locales asumidas en
  `America/Lima`.
- **Nulabilidad:** en ORM 2.0 sale del tipo (`Mapped[str]` → `NOT NULL`).
- **Windows shim:** `if sys.platform == "win32": asyncio.set_event_loop_policy(WindowsSelectorEventLoopPolicy())`
  vive **solo** en el entry point de la app (psycopg3 async no corre bajo ProactorEventLoop).
  No hace falta en Alembic (sync) ni en el contenedor Linux.
- **Secretos:** `.env` gitignoreado; `.env.example` commiteado (plantilla). `uv.lock` se commitea.

---

## 8. Decisiones abiertas / pendientes

- **JSONB vs tablas relacionales** para las partes anidadas del contrato (`signals`,
  `citations`, `debate`). Se decide al modelar `Decision`/`Case`. *(la "decisión jugosa")*
- **Cálculo de confianza:** híbrido — score determinístico desde señales + ajuste del
  Arbiter con justificación. *(definido)*
- **Allowlist de búsqueda web gobernada:** tabla `web_search_allowlist` (dato de
  gobernanza con audit), no env var. Sembrada por migración, cacheada en memoria.
- **Convención de tags de imagen** y **postura de migraciones**: cerrar con el compañero. *(🔶)*

---

## 9. Mapa de archivos actual

```
multiagent-fraud-detection/
├── docker-compose.yml            # (compose.yaml) Postgres + pgvector + healthcheck
├── alembic.ini                   # sqlalchemy.url vacía (la inyecta env.py)
├── migrations/
│   ├── env.py                    # lee DATABASE_URL desde settings (sync)
│   └── versions/                 # c558... pgvector · b2a8... transactions
├── .env / .env.example / .gitignore
├── pyproject.toml / uv.lock / .python-version   # Python 3.12, uv_build
└── src/multiagent_fraud_detection/
    ├── enums.py                  # Channel (StrEnum)
    ├── config/settings.py
    ├── db/
    │   ├── base.py               # Base (DeclarativeBase)
    │   ├── session.py            # engine async + get_session
    │   └── models/
    │       ├── __init__.py       # registra modelos para autogenerate
    │       └── transaction.py    # Transaction (ORM)
    └── schemas/
        └── transaction.py        # TransactionIn (Pydantic)
```

---

## 10. Qué sigue

1. **`CustomerBehavior`** de punta a punta (entidad plana; primer roce con listas →
   `usual_countries`, `usual_devices`).
2. **`Decision` / `Case`** → aquí se resuelve **JSONB vs relacional**.
3. **El grafo:** diseñar el `State` (distinto del `CaseDetail`: memoria de trabajo interna
   vs frontera pública), nodos = agentes, edges condicionales, checkpointer.
4. RAG (chunk + embed de políticas) → API FastAPI → HITL (interrupt + cola) → harness de
   evaluación (entregable 7) → CI (entregable 5).

---

## Documentación asociada

- `contrato_de_interfaz_v0.2.md` — contrato completo (operativo + API).
- Diagrama **Capa 1** (draw.io) — vista Container: tubería construida + pendientes.
- Diagrama de apoyo (draw.io) — recorrido de `Transaction` por la infra.
- Sistema de documentación adoptado: **C4** (Context → Container → Component → Code) como
  columna estructural, más vistas dinámicas (máquina de estados del grafo, ciclo del caso).
  Se documenta **incrementalmente**, al cerrar cada etapa.
