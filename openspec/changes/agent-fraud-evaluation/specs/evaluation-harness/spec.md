## Purpose

Define el evaluador del proyecto académico: cómo corre el sistema contra el
ground truth del dataset, qué métricas produce por política y por decisión, cómo
compara enfoques y qué garantiza la reproducibilidad de la corrida.

## ADDED Requirements

### Requirement: Evaluación contra el ground truth
El sistema SHALL poder correr el grafo de agentes sobre un conjunto de
transacciones y comparar cada decisión emitida contra la decisión esperada de
`ground_truth.csv`, usando la misma precedencia de `DecisionType` del contrato.

#### Scenario: Comparación de decisiones
- **WHEN** el evaluador procesa una transacción con decisión esperada conocida
- **THEN** clasifica el resultado del sistema como acierto o discrepancia respecto
  de la esperada

#### Scenario: Acierto sin etiqueta esperada
- **WHEN** el sistema emite `APPROVE` sobre una transacción sin políticas
  aplicables en el ground truth
- **THEN** el evaluador lo cuenta como acierto

### Requirement: Métricas por decisión y por política
El evaluador SHALL reportar precisión, recall y F1 tanto por valor de decisión
como por política del catálogo, sobre la misma base del ground truth.

#### Scenario: Métricas por política
- **WHEN** se evalúa una corrida sobre la muestra
- **THEN** el reporte incluye precisión, recall y F1 por cada política de la
  muestra

#### Scenario: Métricas por decisión
- **WHEN** se evalúa una corrida sobre la muestra
- **THEN** el reporte incluye precisión, recall y F1 por cada valor de decisión

### Requirement: Muestreo estratificado
El evaluador SHALL seleccionar la muestra de evaluación con muestreo
estratificado para que las políticas menos frecuentes y los casos límite queden
representados, y SHALL documentar el criterio de estratificación y el tamaño de
muestra.

#### Scenario: Políticas poco frecuentes representadas
- **WHEN** una política tiene pocos positivos en el dataset
- **THEN** el muestreo asegura que el subconjunto evaluado contenga suficientes
  positivos de esa política para que su F1 sea significativo

### Requirement: Comparación de enfoques
El evaluador SHALL poder medir el mismo grafo con más de una implementación de un
agente intercambiable —al menos Transaction Context determinístico vs. con LLM—
y reportar los resultados de ambos enfoques sobre el mismo ground truth.

#### Scenario: Context determinístico vs. Context con LLM
- **WHEN** se corre el grafo con Transaction Context determinístico y luego con
  Transaction Context basado en LLM
- **THEN** el evaluador reporta las métricas de ambas corridas por separado y su
  comparación

### Requirement: Reproducibilidad de la corrida
Una corrida de evaluación sobre una muestra dada SHALL ser reproducible: mismo
resultado de métricas al repetirse, salvo el no determinismo acotado de los
agentes con LLM.

#### Scenario: Mismo seed, mismo resultado
- **WHEN** el evaluador se corre dos veces con la misma muestra y el mismo seed
- **THEN** produce el mismo conjunto de señales determinísticas y las mismas
  decisiones de los agentes de lógica pura

### Requirement: Reporte de salida
El evaluador SHALL emitir un reporte legible por persona con el resumen de
métricas, el tamaño de muestra, la lista de enfoques comparados y la versión del
catálogo de políticas usado.

#### Scenario: Reporte generado
- **WHEN** termina una corrida de evaluación
- **THEN** el evaluador emite el reporte con métricas, tamaño de muestra, enfoques
  comparados y versión del catálogo
