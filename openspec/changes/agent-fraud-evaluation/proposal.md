## Why

El esqueleto del grafo de agentes ya existe — diez nodos con contrato de retorno
definitivo, topología, persistencia e invariantes— pero **ningún agente implementa
lógica**: todos son stubs que escriben constantes. Para el proyecto académico hace
falta el sistema multi-agente funcional con LangGraph y LangChain que evalúe el
riesgo de fraude de transacciones de pago, con observabilidad en LangSmith y una
evaluación reproducible contra el ground truth, que es lo que sostiene los
entregables 2, 3, 4, 6 y 7 de la rúbrica.

## What Changes

- **Agentes determinísticos**: se implementa la lógica pura de los tres agentes
  sensores —Transaction Context, Behavioral Pattern y Evidence Aggregation— que
  evalúan las 10 políticas del catálogo contra la transacción, el perfil y el
  historial, respetando el invariante *as-of*, la hora local del cliente, la
  moneda de la cuenta y la precedencia de `DecisionType`.
- **Agentes con LLM**: se implementan los seis agentes de juicio con LangChain —
  Internal Policy RAG (recuperación semántica sobre pgvector), External Threat
  Intel, Debate Pro-Fraude, Debate Pro-Cliente, Decision Arbiter y
  Explainability— con la estrategia de prompting documentada y justificada.
- **Observabilidad con LangSmith**: el grafo se instrumenta para trazar cada
  corrida —inputs, outputs, supersteps, llamadas a LLM, tokens, fallos
  degradados— y habilitar el monitoreo de métricas de producción (entregable 6).
- **Harness de evaluación**: se construye el evaluador que corre el grafo sobre
  una muestra del dataset, compara cada decisión contra `ground_truth.csv` y
  reporta precisión, recall, F1 por política y por decisión, incluyendo la
  comparación de enfoques Context determinístico vs. Context con LLM que promete
  el ADR-0006.
- **Dependencias y configuración**: se agregan `langchain`, el/los proveedor(es)
  de modelo y `langsmith` a `pyproject.toml`, y las variables de entorno
  correspondientes (`ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `LANGSMITH_*`).

Fuera de alcance deliberado: API FastAPI, dashboard, contenerización, CI/CD y
despliegue (frontend, backend e infraestructura se hacen en una etapa posterior).

## Capabilities

### New Capabilities
- `deterministic-agents`: comportamiento requerido de los agentes de lógica pura
  (Transaction Context, Behavioral Pattern, Evidence Aggregation): qué señales
  producen, con qué invariantes (as-of, zona horaria, moneda, precedencia) y cómo
  componen `risk_score` y `base_confidence`.
- `llm-agents`: comportamiento requerido de los agentes con LLM (Policy RAG,
  Threat Intel, Debate ×2, Arbiter, Explainability): entradas, salidas, formato
  estructurado, degradación ante fallo y la cita como autorización del veredicto.
- `observability`: requisitos de trazabilidad y monitoreo con LangSmith sobre el
  grafo: qué se captura por corrida y por llamada a LLM, y qué permite medir en
  producción y en evaluación.
- `evaluation-harness`: requisitos del evaluador contra el ground truth: muestreo
  estratificado, métricas por política y por decisión, comparación de enfoques y
  reproducibilidad de la corrida.

### Modified Capabilities
- Ninguna: `openspec/specs/` no tiene especificaciones previas.

## Impact

- **Código**: `agents/src/graph/nodes.py` (reemplazo de stubs), nuevo
  `agents/src/domain/policies.py` (reglas puras compartidas), nuevo
  `agents/src/llm/` (providers, prompts, esquemas de salida), extensión de
  `agents/src/graph/context.py` (proveedores, vector store, allowlist),
  `agents/src/graph/state.py` (claves nuevas si hicieran falta).
- **Persistencia**: se consume `web_search_allowlist` (pendiente de modelar) y
  `merchant_blacklist`; pgvector ya habilitado para el RAG de políticas.
- **Configuración**: nuevas variables de entorno para claves de API y LangSmith;
  nuevas dependencias en `pyproject.toml`.
- **Repositorios**: se crea `agents/scripts/` harness de evaluación.
- **Docs**: se actualiza `contrato_de_interfaz.md` y los ADR si el diseño cierra
  decisiones nuevas.
