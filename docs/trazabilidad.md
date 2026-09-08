# Trazabilidad — rúbrica y enunciado

Vincula cada ítem de [`requisitos/rubrica.md`](requisitos/rubrica.md) con la
evidencia que lo cubre en el repo, y declara los desvíos frente a
[`requisitos/reto_de_aplicacion.md`](requisitos/reto_de_aplicacion.md).

> Los dos documentos de `requisitos/` son de un tercero y **no se editan**, igual
> que los documentos normativos del catálogo (ADR-0007). Este archivo es su
> vinculación: lo nuestro, con dueño y fecha.
>
> **Se revisa al cerrar cada etapa**, como los diagramas. Una trazabilidad
> desactualizada es peor que ninguna: sugiere cobertura donde no la hay.

---

## Los doce ítems

| # | Ítem | Evidencia | Estado |
|---|---|---|---|
| 1 | Descripción del caso de uso | `README.md`, `requisitos/reto_de_aplicacion.md` | 🟡 falta el informe |
| 2 | Selección de modelo y datos | ADR-0003 (dataset sintético), ADR-0012 (índice versionado), `data/README.md`, tres proveedores tras puerto (`Embedder`, `Narrator`, `Searcher`) | ✅ |
| 3 | Ingeniería de prompts y adaptación | `explain/customer.py` (`PROMPT_VERSION`), `intel/snapshot.py` (`QUERY_TEMPLATE`), `debate/pro_fraud.py`, `debate/pro_customer.py`, `arbiter/prompt.py` (ADR-0016), `retrieval/` (RAG sobre pgvector), ADR-0011, ADR-0012, ADR-0014 | 🟡 ver desvío D-04 |
| 4 | Implementación de la aplicación | `graph/`, `domain/`, `db/`, `api/`, `dashboard/`, `diagrams/c4-container.drawio`, `contrato_de_interfaz.md` (v0.13) | ✅ |
| 5 | Orquestación y despliegue | ADR-0008 (digest), ADR-0009 (migraciones), ADR-0010 (seed), ADR-0021 (Azure), ADR-0022 (GCP), `infra/azure/`, `infra/gcp/`, `.github/workflows/`, contrato §1 | ✅ |
| 6 | Monitoreo y mantenimiento | LangSmith, contrato §3.3 (cuatro métricas operativas), cinco sellos de auditoría en `decisions`, tarjeta de costo/latencia en vivo (ADR-0019/0020), cola HITL en `dashboard/` | ✅ |
| 7 | Evaluación de la aplicación | `check_policies.py` 7000/7000, ADR-0006 + ADR-0016 (brazo de control determinístico, ya en producción — no sólo planeado), ADR-0013 (métricas duras vs LLM-as-judge), `ground_truth.csv` | 🟡 |
| 8 | Resultados y demostración | `smoke_decision.py`, `smoke_retrieval.py`, `smoke_api.py`, `smoke_agents.py`, demo en vivo (Azure + GCP, ver README) | 🟡 falta el video |
| 9 | Conclusiones | `docs/reviews/` (doce actas) — la materia prima ya está escrita | ⬜ |
| 10 | Recomendaciones | deudas declaradas: event-driven, feed en streaming, consolidación de listas de gobernanza, retry propio con backoff en el proveedor de embeddings (Gemini, ver acta 11) | ⬜ |
| 11 | Referencias (≥5, APA) | — | ⬜ **nadie las está juntando** |
| 12 | Video de exposición | — | ⬜ |

---

## Desvíos declarados frente al enunciado

Ninguno es una omisión: cada uno tiene su razón escrita y va al informe como
limitación argumentada, que puntúa más que el silencio.

| # | Desvío | Dónde está la razón |
|---|---|---|
| D-01 | El enunciado muestra **dos** políticas de ejemplo; el sistema implementa **once**, con documento y vinculación separados | ADR-0007 |
| D-02 | **FP-10 no se mide.** Está implementada y es citable, pero su ground truth no es reproducible | ADR-0005, ADR-0015 |
| D-03 | La **búsqueda web ocurre en build**, no durante el análisis del caso. El paso 5 del flujo de ejemplo describe lo segundo | ADR-0014 |
| D-04 | **No hay fine-tuning ni LoRA.** El ítem 3 los nombra como opciones; la adaptación del sistema es RAG y prompting versionado. Ajustar un modelo sobre once políticas sintéticas mediría el sobreajuste, no la capacidad | pendiente de ADR o nota en el informe |
| D-05 | ~~El Arbiter es determinístico en la etapa actual~~ — **resuelto**: desde ADR-0016 (06-ago) el Arbiter tiene LLM y usa la precedencia determinística como *piso*, no como veredicto final. Queda acá, tachado, en vez de borrarse, para que quede registro de que fue una limitación real y ya no lo es | ADR-0006 (rol original), ADR-0016 (resolución) |
| D-06 | `issuer_bank` no se modelaba por falta de consumidor; ahora sí | ADR-0015 |

> **D-04 es el único sin respaldo escrito.** Es el que más fácil se lee como
> "no lo hicieron" en vez de "decidieron no hacerlo".

---

## Lo que falta empezar ya

**Ítem 11 — referencias.** Mínimo cinco en APA, citadas en el texto. Hoy no hay
ninguna registrada y la bibliografía se está usando sin anotarse: noisy-OR para
el `risk_score`, la literatura de RAG, la de LLM-as-judge. Reconstruirlas al
final cuesta más y sale peor.

Propuesta: `docs/referencias.md`, una entrada por fuente **en el momento en que se
usa**, con el lugar del repo que la consume. Es el mismo principio que hace que
las actas de etapa se escriban al cerrar y no al terminar el proyecto.
