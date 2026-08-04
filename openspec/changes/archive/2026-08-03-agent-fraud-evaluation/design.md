## Context

El grafo ya está cableado y persistido (ver proposal.md — Why): diez nodos con
contrato de retorno definitivo, `@degrades`, topología de dos olas, invariantes
as-of/veredicto en `nodes.py`, y un dataset de 7 000 transacciones con ground
truth. Todo lo que esta etapa agrega son los motores de los agentes y el
evaluador, sin tocar el cableado. Restricciones heredadas:

- Los nodos de evidencia degradan, no lanzan; el reintento vive en el cuerpo del
  nodo (ADR-0006, repaso 03 §2.3/2.4).
- El reparto determinístico/LLM ya está decidido (ADR-0006): Context,
  Behavioral y Aggregation son puros; RAG, Threat Intel, Debate ×2, Arbiter y
  Explainability usan LLM.
- `risk_score` no es ajustable por el Arbiter y la confianza es híbrida
  (contrato §2.5). El invariante *as-of* se hace cumplir en el repositorio.
- El evaluador debe ser reproducible: el no determinismo solo puede venir de los
  agentes con LLM, y solo donde el ground truth lo permita.
- El proveedor LLM es configurable por entorno: en **dev** apunta al endpoint
  `opencode.ai/zen/go/v1` (API compatible con Anthropic vía SDK de OpenAI, según
  `agents/.env`) y en el **despliegue** se reemplaza por la API real de Claude.
  Los embeddings usan Gemini (`gemini-embedding-2`, 3072 dimensiones nativas).
- MLflow registra los experimentos en un **servidor remoto propio**
  (`https://mlflow.chris-co.net`, autohosteado y sin autenticación); el harness
  apunta ahí el tracking URI, separado del motor.
- **Runtime objetivo (etapa de infraestructura)**: el grafo se invoca **una
  transacción por llamada**, disparado por SQS hacia una Lambda empaquetada en
  Docker. El entrypoint actual (`build_graph().ainvoke` por caso) ya satisface
  esa forma; el handler, el Dockerfile y el consumo de SQS quedan fuera de
  alcance de esta etapa.

## Goals / Non-Goals

**Goals:**
- Implementar los tres agentes puros como funciones contra un módulo de dominio
  `domain/policies.py` con las diez políticas del catálogo.
- Implementar los seis agentes con LLM con salida estructurada y degradación.
- Trazar con LangSmith vía configuración de entorno, sin tocar los nodos.
- Un harness reproducible que mida precisión/recall/F1 por política y por
  decisión, con muestreo estratificado y comparación de enfoques.
- Registrar cada corrida de evaluación en MLflow (métricas de agentes y del
  retrieval) en el servidor remoto propio (`https://mlflow.chris-co.net`).

**Non-Goals:**
- API FastAPI, dashboard, Docker, CI/CD, despliegue (etapa posterior).
- Modelar `web_search_allowlist` como tabla *funcionante* contra web real:
  esta etapa define su modelo y su consumo, pero en evaluación la consulta
  externa se ejecuta en modo offline (ver Decisión D6).
- Fine-tuning del modelo (solo prompting + RAG).

## Decisions

### D1. Lógica de políticas en `domain/policies.py`, separada del ground truth
Cada política es una función pura: `(transacción, perfil, historial) -> señal |
ninguna`, con una sola precedencia de `DecisionType` compartida como constante.
`build_ground_truth.py` **no** importa estas funciones: el harness debe medir la
calidad del sistema, no validar el sistema contra sí mismo (repaso 04 §9 pregunta
2). Se comparte solo lo que el contrato exige compartir —la precedencia y los
factores de moneda—, nunca la lógica de detección.

**Alternativas**: extraer el código del script y que ambos lo importen (descartada:
la comparación mediría la discrepancia de reglas, no la calidad); duplicar hasta
la precedencia (descartada: el harness castigaría al sistema por acertar).

### D2. Reparto de políticas entre Transaction Context y Behavioral Pattern
Cuatro políticas necesitan historial (secuencia), cinco necesitan perfil, una
solo la transacción (repaso 04 §9 pregunta 4):

- **Transaction Context** — solo transacción y lista negra: `FP-07`.
- **Behavioral Pattern** — perfil e historial: `FP-01`, `FP-02`, `FP-03`,
  `FP-04`, `FP-05`, `FP-06`, `FP-08`, `FP-09`, `FP-11`.

Ambos delegan en `domain/policies.py`; la diferencia es qué insumo trae cada
nodo (perfil recuperado por `customer_id`, historial por cliente y por
dispositivo). Esto mantiene la topología actual sin aristas nuevas.

### D3. `GraphContext` crece, no el estado
`GraphContext` gana los servicios que los nodos con LLM y el RAG necesitan:
factory de sesión (ya existe), proveedor de LLM, cliente de embeddings/vector
store y repositorio de allowlist. Los LLM no entran al `GraphState` porque no son
serializables ni se persisten; el estado solo transporta evidencia. MLflow **no**
entra al `GraphContext`: el tracking es responsabilidad exclusiva del harness (D9).

### D4. Salida estructurada con validación en el nodo
Cada agente con LLM usa `with_structured_output` (esquema Pydantic por nodo) y el
nodo **valida el resultado antes de escribirlo al estado**: un fallo de schema se
trata como fallo del agente (degradación), no como texto crudo. El Arbiter, además,
re-verifica los invariantes del contrato (respaldo interno + score determinístico)
antes de devolver; la guarda del persistidor sigue existiendo como red.

### D5. Scoring determinístico con `scoring_version`
- `risk_score` = combinación monótona de severidades (pesos `high=1.0`,
  `medium=0.5`, `low=0.25`, saturado a `[0,1]`), establecido en
  `domain/scoring.py`.
- `base_confidence` = forma de U sobre el riesgo: máxima en extremos limpios,
  mínima en evidencia contradictoria, y un factor reductor cuando hay agentes
  degradados. `scoring_version` identifica la fórmula; cambia si la fórmula
  cambia. El delta acotado del Arbiter se aplica sobre `base_confidence`.

**Alternativa**: ajuste de confianza libre por el LLM (descartada por el
contrato §2.5 — `risk_score` no ajustable, confianza híbrida).

### D6. Threat Intel gobernada y offline en evaluación
`web_search_allowlist` se modela como tabla (migración + modelo + seed con un
conjunto pequeño de dominios), y el nodo Threat Intel solo consulta dominios de la
lista, cacheando en memoria con invalidación al escribir (contrato §4). Para
reproducibilidad, el harness corre con `THREAT_INTEL_OFFLINE=true`: el nodo
devuelve citas externas vacías y registra la omisión, como exige ADR-0005. En
producción el flag se apaga.

### D7. Harness: `scripts/evaluate.py`
- Lee `ground_truth.csv`, estratifica por política y por decisión (piso de
  positivos por política; seed fijo para reproducibilidad).
- Por cada transacción muestreada: crea el caso vía `build_graph().ainvoke` con
  `GraphContext` inyectado, compara `decision` contra `expected_decision`, y
  acumula por política y por decisión.
- Reporte: precisión, recall, F1 por política y por decisión, tamaño de muestra,
  enfoques comparados y versión del catálogo.
- Modo comparación: corre el grafo con Transaction Context determinístico y con
  Transaction Context basado en LLM (intercambiable por configuración), y reporta
  ambos (ADR-0006).
- Además del reporte local, cada corrida se registra en MLflow (D9).

### D8. Almacén vectorial: tabla `policy_chunks`
El corpus del RAG de políticas se guarda en una tabla nueva `policy_chunks`, la
única del esquema con columna vectorial:

| Columna | Tipo | Notas |
|---|---|---|
| `chunk_id` | `str` PK | id del chunk dentro de la política |
| `policy_id` | `str` | del catálogo (`FP-01`…) |
| `version` | `str` | del catálogo (`2025.1`) |
| `content` | `text` | texto del chunk |
| `embedding` | `vector(3072)` | del `gemini-embedding-2`, **dimensión nativa** |
| `metadata` | `jsonb` | descriptor, severidad sugerida, acción |

**Sin índice vectorial a propósito.** pgvector 0.7 no permite HNSW/IVFFlat por
encima de 2000 dimensiones, y 3072 lo excede. Con un corpus de 11 políticas, el
scan coseno secuencial es instantáneo y exacto (no aproximado); se revisa el
día que el corpus crezca lo suficiente para necesitar un índice. La
recuperación pasa siempre por `db/repositories/policy_rag.py`, que usa `<=>`
(1 − coseno). Se alimenta con el script de indexación que lee
`data/policies/fraud_policies_2025.1.json` (chunking del JSON, embeddings y
carga; tarea 5.3). `web_search_allowlist` y `merchant_blacklist` **no** son
vectoriales: son lookups puntuales (D6, FP-07).

### D9. Experimentación con MLflow sobre servidor remoto
Se agrega `mlflow` como dependencia. El harness configura el tracking URI en
`MLFLOW_TRACKING_URI=https://mlflow.chris-co.net` (servidor propio,
autohosteado, sin autenticación) y registra por corrida:

- **Parámetros**: enfoque (Context determinístico vs. LLM), `--sample-size`,
  seed, versión del catálogo, `scoring_version`, `LLM_PROVIDER`.
- **Métricas**: precisión/recall/F1 por decisión y por política, y métricas del
  retrieval (recall@k de políticas relevantes).
- **Tags**: entorno (dev/despliegue), fecha, commit si existe.

El servidor remoto gestiona su propio backend; **no hay base `mlflow` local**
ni Alembic que la toque. Si `MLFLOW_TRACKING_URI` no está seteado, el harness
corre igual y no registra nada. El grafo no depende de MLflow: el tracking vive
en el harness (D3).

### D10. Proveedor LLM configurable por entorno
Una factory de proveedor lee la configuración y construye el cliente LLM:

- **Dev**: `ANTHROPIC_API_BASE=https://opencode.ai/zen/go/v1`,
  `ANTHROPIC_API_KEY=…`, `ANTHROPIC_MODEL=…` (API compatible con Anthropic vía
  SDK de OpenAI, según `agents/.env`).
- **Despliegue**: la misma factory apunta a la API real de Claude con la clave
  propia.

`LLM_PROVIDER` selecciona el adaptador (o el `base_url`/modelo se leen directo de
las variables). Los prompts y los esquemas de salida estructurada **no cambian**
entre entornos: solo cambia el cliente. Los embeddings siempre usan Gemini
(`EMBEDDING_MODEL`, `EMBEDDING_DIM`).

## Evaluación del esquema actual para el sistema de agentes

Revisado `agents/src/db/models/` contra los agentes y el retrieval que esta etapa
implementa. El esquema de 8 tablas es **conveniente**: cubre sensores, evidencia,
decisión, HITL y gobernanza sin rediseñar ninguna tabla.

| Necesidad | Tabla | Veredicto |
|---|---|---|
| Perfil del cliente (Context/Behavioral, FP-01…FP-09, FP-11) | `customer_behaviors` | ✅ suficiente (7 campos de evaluación ya modelados) |
| Historial *as-of* (FP-03/04/05/11) | `transactions` + 2 índices compuestos | ✅ suficiente |
| Lista negra (FP-07) | `merchant_blacklist` | ✅ suficiente |
| Caso + snapshot congelado | `cases` | ✅ suficiente |
| Decisión, señales, errores | `decisions`, `signals`, `agent_errors` | ✅ suficiente |
| HITL | `human_resolutions` | ✅ suficiente |
| Corpus del RAG | `policy_chunks` | 🆕 **falta** (D8) |
| Allowlist de búsqueda web | `web_search_allowlist` | 🆕 **falta** (D6, ya prevista) |
| Backend de experimentos | servidor remoto `mlflow.chris-co.net` | (D9, sin base local) |

Conclusiones: (1) no hay que tocar ninguna tabla existente — los agentes se
apoyan en lo ya modelado; (2) el único almacenamiento vectorial requerido es el
corpus de políticas (`policy_chunks`), no hay otras búsquedas semánticas en el
alcance; (3) MLflow corre en un servidor remoto propio, que no compite con el
esquema del motor.

## Risks / Trade-offs

- **[Comparación injusta con el ground truth]** → Precedencia y factores de
  moneda compartidos como constantes; la lógica de detección queda separada a
  propósito (D1).
- **[No determinismo de LLM rompe el harness]** → Muestreo con seed fijo, agentes
  puros deterministas, Threat Intel offline en evaluación (D6); el F1 de las
  señales se mide sobre lo determinístico.
- **[Costo y latencia de seis llamadas a LLM por caso]** → Muestra estratificada
  acotada y parametrizable (`--sample-size`), fallos degradan sin re-intentar el
  caso completo.
- **[Modelo con salida inválida]** → `with_structured_output` + validación en el
  nodo degradan en lugar de envenenar el estado (D4).
- **[Duplicación de lógica entre ground truth y agentes]** → Dos implementaciones
  son la decisión, no un descuido; cada una se testea contra su propio fixture.
- **[RAG sobre un catálogo de 11 políticas es sobredimensionado]** → El valor
  académico es el pipeline completo (embeddings → pgvector → recuperación →
  cita); el tamaño no cambia el diseño.
- **[Servidor MLflow sin autenticación]** → `https://mlflow.chris-co.net` está
  abierto: cualquiera con acceso a la red podría leer o escribir experimentos.
  Mitigación: el entorno es de evaluación y los experimentos no contienen PII de
  clientes (solo métricas y parámetros agregados); se revisa si el servidor va a
  producción. Tarea de verificación en el harness (9.4).
- **[Dev (opencode) ≠ despliegue (Claude)]** → El contrato de salida de los agentes
  con LLM puede variar entre proveedores. Mitigación: salida estructurada con
  validación en el nodo (D4) y evaluación comparativa de enfoques en ambos
  entornos como parte del entregable 7.

## Migration Plan

- Migraciones nuevas: `web_search_allowlist` (D6) y `policy_chunks` (D8) — van
  detrás de `1276e208c3d9` (head actual). `alembic upgrade head && alembic check`.
- Sin base de MLflow local: el tracking apunta al servidor remoto
  (`https://mlflow.chris-co.net`), que gestiona su propio backend; nada de MLflow
  pasa por Alembic ni por las migraciones del motor.
- No hay cambios de schema en tablas existentes; el persistidor se mantiene.
- Las funciones de nodo se reemplazan una a una bajo su firma actual; `smoke_graph.py`,
  `smoke_degradation.py` y `smoke_persistence.py` deben seguir pasando.

## Open Questions

- Ninguna que cambie specs, enfoque o tareas: el proveedor de modelo ya está
  definido por entorno (D10), el almacén vectorial es una sola tabla (D8), y el
  piso exacto de la estratificación se ajusta con el reporte de la primera corrida.
