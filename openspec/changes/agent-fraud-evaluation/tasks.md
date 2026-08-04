## 1. Dependencias y configuración

- [x] 1.1 Agregar `langchain`, `langchain-anthropic`, `langchain-google-genai`, `langsmith` y `mlflow` a `pyproject.toml` (y sincronizar el lock con `uv lock`)
- [x] 1.2 Agregar al `Settings` las variables de entorno nuevas: `ANTHROPIC_API_BASE`, `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, `GEMINI_API_KEY`, `EMBEDDING_MODEL`, `EMBEDDING_DIM`, `MLFLOW_TRACKING_URI`, `LANGSMITH_API_KEY`, `LANGSMITH_TRACING`, `LANGSMITH_PROJECT`, `LLM_PROVIDER`, `THREAT_INTEL_OFFLINE`
- [x] 1.3 Documentar las variables nuevas en `contrato_de_interfaz.md` §1.4

## 2. Capa de dominio determinística

- [x] 2.1 Crear `src/domain/constants.py` con la precedencia de `DecisionType` y los factores de moneda de referencia compartidos
- [x] 2.2 Crear `src/domain/policies.py` con una función pura por política del catálogo (FP-01…FP-09, FP-11) que reciba transacción, perfil e historial y devuelva señal o nada
- [x] 2.3 Crear `src/domain/scoring.py` con la fórmula de `risk_score` (monótona en severidades) y de `base_confidence` (forma de U, con factor reductor por degradación), más `scoring_version`
- [x] 2.4 Agregar test unitario por política sobre fixtures explícitos (monto/horario, internacional+dispositivo, velocity, card testing, geo, canal, blacklist, cuenta nueva, cambio de perfil, smurfing)
- [x] 2.5 Agregar test del scoring: monotonía del riesgo, forma de U de la confianza y reducción por agentes degradados

## 3. Modelos y repositorios nuevos

- [x] 3.1 Crear modelo y migración de `web_search_allowlist` (detrás del head actual) y seed con un conjunto pequeño de dominios
- [x] 3.2 Crear repositorio de `web_search_allowlist` con cache en memoria e invalidación al escribir
- [x] 3.3 Crear repositorio de `merchant_blacklist` con lookup puntual por `merchant_id`
- [x] 3.4 Crear modelo y migración de `policy_chunks` con columna `embedding vector(3072)` y sin índice vectorial (pgvector no soporta >2000 dims; scan coseno exacto) (D8)
- [x] 3.5 Verificar `alembic upgrade head && alembic check` y `smoke_seed.py` siguen pasando

## 4. Agentes determinísticos

- [x] 4.1 Implementar el nodo Transaction Context evaluando FP-07 contra la transacción y la lista negra
- [x] 4.2 Implementar el nodo Behavioral Pattern recuperando perfil e historial (cliente y dispositivo) y evaluando FP-01…FP-06, FP-08, FP-09, FP-11, con el invariante *as-of* desde `transaction_history.py`
- [x] 4.3 Implementar el nodo Evidence Aggregation: deduplicar señales por `code` usando `emitted_by`, aplicar orden determinístico y calcular `risk_score` + `base_confidence`
- [x] 4.4 Verificar que `smoke_graph.py`, `smoke_degradation.py` y `smoke_persistence.py` pasan con los nodos reales

## 5. Infraestructura LLM y RAG

- [x] 5.1 Extender `GraphContext` con proveedor de LLM, cliente de embeddings/vector store y repositorio de allowlist
- [x] 5.2 Crear factory de proveedor LLM por entorno (`LLM_PROVIDER`): dev = API compatible con Anthropic vía opencode, despliegue = Claude (D10)
- [x] 5.3 Crear índice del catálogo de políticas en `policy_chunks`: chunking del JSON, embeddings (Gemini) y carga
- [x] 5.4 Implementar el nodo Internal Policy RAG: query híbrida (señales + descriptor de transacción), recuperación y producción de `citations_internal`
- [x] 5.5 Implementar el nodo External Threat Intel: consulta solo contra el allowlist, citas externas o descartes registrados, respetando `THREAT_INTEL_OFFLINE`

## 6. Agentes con LLM

- [x] 6.1 Implementar Debate Pro-Fraude con salida estructurada (`pro_fraud_argument`) sobre la evidencia agregada
- [x] 6.2 Implementar Debate Pro-Cliente con salida estructurada (`pro_customer_argument`) sobre la evidencia agregada
- [x] 6.3 Implementar el Decision Arbiter con salida estructurada: veredicto, ajuste acotado de confianza con justificación, respetando la precedencia y degradando a `ESCALATE_TO_HUMAN` sin respaldo interno
- [x] 6.4 Implementar Explainability con salida estructurada: `explanation_customer` y `explanation_audit` fundamentadas
- [x] 6.5 Verificar que una salida inválida de un LLM degrada el agente y no envenena el estado (extensión de `smoke_degradation.py`)

## 7. Observabilidad con LangSmith

- [x] 7.1 Configurar el trazado automático del grafo por variables de entorno (`LANGSMITH_*`) sin tocar los nodos
- [x] 7.2 Verificar que cada corrida queda asociada al proyecto configurado y que las llamadas a LLM registran prompt, respuesta, tokens y latencia
- [x] 7.3 Verificar que el trazado desactivado no rompe la corrida
- [x] 7.4 Documentar las métricas observables (frecuencia de degradación, decisiones degradadas, distribución de decisiones y de `risk_score`) para el entregable 6

## 8. Harness de evaluación

- [x] 8.1 Crear `scripts/evaluate.py`: muestreo estratificado por política y decisión con seed fijo
- [x] 8.2 Implementar la corrida del grafo por transacción muestreada y la comparación contra `ground_truth.csv` con la precedencia compartida
- [x] 8.3 Reportar precisión, recall y F1 por política y por decisión, tamaño de muestra, enfoques comparados y versión del catálogo
- [x] 8.4 Implementar el modo comparación: Context determinístico vs. Context con LLM sobre la misma muestra (ADR-0006)
- [x] 8.5 Verificar reproducibilidad: dos corridas con el mismo seed producen el mismo resultado en los agentes determinísticos
- [x] 8.6 Correr el harness y guardar el reporte de la corrida de referencia en `agents/docs/reviews/` como evidencia del entregable 7

## 9. Experimentación con MLflow

- [x] 9.1 Configurar el tracking URI de MLflow apuntando al servidor remoto (`MLFLOW_TRACKING_URI=https://mlflow.chris-co.net`); sin base local
- [x] 9.2 Registrar en MLflow por corrida: parámetros (enfoque, `--sample-size`, seed, versión del catálogo, `scoring_version`, `LLM_PROVIDER`) y métricas (precisión/recall/F1 por decisión y por política)
- [x] 9.3 Implementar métricas del retrieval (recall@k de políticas relevantes) y registrarlas en MLflow
- [x] 9.4 Verificar que las corridas llegan al servidor remoto de MLflow y no interfieren con el motor `fraud`
- [x] 9.5 Documentar en `contrato_de_interfaz.md`/README la convención de experimentos (nombres, tags dev/despliegue) para el entregable 7
