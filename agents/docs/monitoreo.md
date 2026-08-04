# Monitoreo y métricas observables — Entregable 6

> Qué mide el sistema en producción, de dónde sale cada métrica y cómo se
> vigila. LangSmith traza **cada corrida** del grafo (tarea 7); la persistencia
> en `decisions`, `signals` y `agent_errors` es la fuente de las métricas
> agregadas.

## Fuentes de las métricas

| Fuente | Qué captura | Notas |
|---|---|---|
| LangSmith (`LANGSMITH_TRACING=true`) | Corrida por caso, llamadas a LLM (prompt, respuesta, tokens, latencia) | Se exporta desde `Settings` en `src/observability.py` |
| `decisions` | Veredicto, `risk_score`, confianza, versión de scoring | Escrito por el único nodo persistidor |
| `signals` | Señales por caso (código, severidad) | La unidad de evaluación del entregable 7 |
| `agent_errors` | Fallos por agente (agente, tipo, mensaje, instante) | Índice en `agent` para `GROUP BY agent` |

## Métricas de producción

### Degradación
- **Frecuencia de fallos por agente**: `GROUP BY agent` sobre `agent_errors`.
- **Decisiones degradadas**: proporción de casos con `degraded_agents` no vacío
  (derivable: `agent_errors.case_id` distinct).
- Un agente que cae **debe** verse como una suba de estas métricas, no como una
  baja de decisión: la degradación es el diseño, no el accidente.

### Distribución de decisiones
- Proporción de `APPROVE` / `CHALLENGE` / `BLOCK` / `ESCALATE_TO_HUMAN` por
  período. Un cambio brusco en la mezcla es señal de drift en los datos de
  entrada o en las políticas.

### Riesgo y confianza
- Distribución de `risk_score` (sospecha) y de `confidence` (seguridad).
- **Deriva de `risk_score`**: como no es ajustable por el Arbiter (contrato
  §2.5), un cambio en su distribución es directamente atribuible a los datos de
  entrada, no al modelo de lenguaje.
- **Deriva de `confidence`**: el gap frente a `base_confidence` y la fracción
  con `confidence_rationale != null` miden cuánto está ajustando el Arbiter.

### Volumen y latencia
- Casos por hora, y p95 de duración del grafo (traza LangSmith por corrida).
- Costo: tokens por corrida (traza LangSmith por llamada a LLM).

## Cómo se vigilan

- **En evaluación** (entregable 7): el harness computa las métricas de calidad
  y las registra en MLflow (tarea 9).
- **En producción** (entregable 6): LangSmith para la traza por corrida y
  consultas SQL sobre las tablas para las agregadas. La convención de
  experimentos MLflow está en `docs/adr/` y en la tarea 9.5.

## Convención de experimentos en MLflow

El harness registra cada corrida en el experimento **`fraud_evaluation`** de
MLflow, con el tracking URI de `MLFLOW_TRACKING_URI`
(`https://mlflow.chris-co.net`, servidor remoto propio, sin autenticación). Por
corrida:

| Qué | Ejemplo |
|---|---|
| **Parámetros** | `modo=deterministic`, `sample_size=60`, `seed=42`, `version_catalogo=2025.1`, `scoring_version=2026.1`, `llm_provider=deterministic` |
| **Métricas** | `precision_<decisión/política>`, `recall_...`, `f1_...`, `recall_retrieval`, `accuracy`, `degradados` |
| **Tags** | `entorno=openai-compatible` (dev) / `anthropic` (despliegue), `threat_intel_offline` |

Reglas:
- **Un run por corrida**, nombrado `<modo>_<seed>` (p. ej. `deterministic_42`).
- El servidor remoto gestiona su propio backend; Alembic del motor solo toca
  `fraud` y no hay base de MLflow local.
- Si `MLFLOW_TRACKING_URI` no está seteado, el harness corre igual y no
  registra nada: los experimentos son un valor agregado, no un bloqueo.

## Regla transversal

> Un invariante que depende de que cada autor lo recuerde no es un invariante.

El `risk_score` determinístico (con `scoring_version`) es lo que hace que las
métricas de drift signifiquen algo: si la fórmula cambiara sin cambiar
`scoring_version`, las distribuciones se mezclarían entre versiones y el drift
sería ruido.
