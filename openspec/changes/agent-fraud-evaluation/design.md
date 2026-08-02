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

## Goals / Non-Goals

**Goals:**
- Implementar los tres agentes puros como funciones contra un módulo de dominio
  `domain/policies.py` con las diez políticas del catálogo.
- Implementar los seis agentes con LLM con salida estructurada y degradación.
- Trazar con LangSmith vía configuración de entorno, sin tocar los nodos.
- Un harness reproducible que mida precisión/recall/F1 por política y por
  decisión, con muestreo estratificado y comparación de enfoques.

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
serializables ni se persisten; el estado solo transporta evidencia.

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

## Migration Plan

- Migración nueva: `web_search_allowlist` (modelo + migración + seed) — va detrás
  de `1276e208c3d9` (head actual). `alembic upgrade head && alembic check`.
- No hay cambios de schema en tablas existentes; el persistidor se mantiene.
- Las funciones de nodo se reemplazan una a una bajo su firma actual; `smoke_graph.py`,
  `smoke_degradation.py` y `smoke_persistence.py` deben seguir pasando.

## Open Questions

- Ninguna que cambie specs, enfoque o tareas: la elección de proveedor LLM se
  resuelve en implementación con una factory por entorno (`ANTHROPIC_API_KEY` /
  `GEMINI_API_KEY`), y el piso exacto de la estratificación se ajusta con el
  reporte de la primera corrida.
