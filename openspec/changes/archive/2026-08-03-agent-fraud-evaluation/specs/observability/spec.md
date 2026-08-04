## Purpose

Define los requisitos de trazabilidad y monitoreo con LangSmith sobre el grafo de
agentes: qué se captura por corrida y por llamada a LLM, para habilitar el
monitoreo de producción y la evaluación del proyecto académico.

## ADDED Requirements

### Requirement: Trazabilidad de la corrida del grafo
El sistema SHALL registrar cada invocación del grafo de agentes en LangSmith,
capturando el caso analizado y el estado de entrada, y SHALL asociar a esa corrida
la actividad de todos sus nodos.

#### Scenario: Caso analizado trazado
- **WHEN** el grafo evalúa un caso
- **THEN** LangSmith registra una corrida por el caso con su entrada de transacción

### Requirement: Captura de llamadas a LLM
Cada llamada a un modelo de lenguaje por parte de los agentes con LLM SHALL quedar
trazada en LangSmith con su prompt, respuesta, uso de tokens y latencia.

#### Scenario: Llamada al modelo trazada
- **WHEN** un agente con LLM invoca al modelo
- **THEN** LangSmith registra el prompt enviado, la respuesta, el conteo de tokens
  y la latencia de la llamada

### Requirement: Visibilidad de supersteps y agentes degradados
El sistema SHALL permitir correlacionar la traza de una corrida con el rastro de
agentes (`agent_route`) y con los agentes degradados del caso.

#### Scenario: Falla degradada visible en la traza
- **WHEN** un agente falla y el caso se analiza degradado
- **THEN** la traza de esa corrida permite identificar el agente fallido y el error
  asociado

### Requirement: Selección de proyecto por entorno
El sistema SHALL dirigir las trazas al proyecto de LangSmith configurado por
entorno y SHALL poder desactivar el trazado explícitamente sin cambios de código.

#### Scenario: Trazado desactivado
- **WHEN** la configuración de trazado está desactivada
- **THEN** el grafo corre sin emitir trazas a LangSmith y sin fallar

#### Scenario: Proyecto configurado
- **WHEN** la configuración define un proyecto de LangSmith
- **THEN** las trazas se asocian a ese proyecto

### Requirement: Métricas observables para monitoreo
El sistema SHALL exponer, a partir de la información trazada y persistida, las
métricas necesarias para el monitoreo de producción: frecuencia de degradación por
agente, decisiones degradadas, distribución de decisiones y de `risk_score`, y
deriva de confianza y de volumen.

#### Scenario: Frecuencia de fallos por agente
- **WHEN** se consulta el monitoreo de un período
- **THEN** se puede obtener con qué frecuencia falla cada agente y qué decisiones
  se tomaron degradadas

#### Scenario: Distribución de decisiones
- **WHEN** se consulta el monitoreo de un período
- **THEN** se puede obtener la distribución de decisiones emitidas y de `risk_score`
