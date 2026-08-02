## Purpose

Define el comportamiento de los seis agentes que usan LLM (LangChain) en el grafo
de fraude: recuperación de políticas, inteligencia externa, debate pro/contra,
arbitraje y explicabilidad, incluyendo sus salidas estructuradas y su
degradación ante fallo.

## ADDED Requirements

### Requirement: Recuperación de políticas como respaldo
El sistema SHALL recuperar, para cada caso, las políticas del catálogo relevantes
a las señales ya detectadas y a la transacción, y SHALL citar cada política
recuperada con su identificador, versión y chunk. El veredicto autónomo SHALL
exigir respaldo interno recuperado.

#### Scenario: Veredicto autónomo sin respaldo
- **WHEN** el agente de decisión emitiría un veredicto autónomo sin políticas
  recuperadas
- **THEN** el sistema degrada la decisión a `ESCALATE_TO_HUMAN` en lugar de emitir
  un veredicto sin cita

#### Scenario: Recuperación semántica sobre catálogo
- **WHEN** el sistema recupera políticas sobre el catálogo indexado
- **THEN** devuelve las políticas aplicables con `policy_id`, `version` y el chunk
  que las sustenta

### Requirement: Inteligencia externa gobernada
El sistema SHALL consultar fuentes externas de alertas de fraude únicamente dentro
de la lista permitida gobernada, y SHALL registrar cada fuente consultada con su
URL, resumen e instante de recuperación, descartando y anotando las rechazadas.

#### Scenario: Fuente fuera de la lista permitida
- **WHEN** una fuente externa no está en la lista permitida
- **THEN** el sistema no la consulta y registra el descarte con su motivo

#### Scenario: Fuente permitida consultada
- **WHEN** una fuente externa está en la lista permitida
- **THEN** el sistema la consulta y registra su URL, resumen e instante en las
  citas externas del caso

### Requirement: Debate pro-fraude y pro-cliente
El sistema SHALL construir dos argumentos en lenguaje natural por cada caso: uno a
favor de sospecha de fraude y otro en descargo del cliente, ambos fundamentados en
la evidencia agregada, y SHALL publicarlos en el resultado del caso.

#### Scenario: Debate sobre evidencia contradictoria
- **WHEN** el caso tiene señales a favor y en contra de fraude
- **THEN** el sistema produce ambos argumentos reflejando la evidencia de cada
  lado, sin omitir las señales del lado contrario

### Requirement: Arbitraje con justificación acotada
El sistema SHALL emitir el veredicto (`APPROVE`, `CHALLENGE`, `BLOCK`,
`ESCALATE_TO_HUMAN`) considerando la evidencia, el debate y el respaldo interno, y
SHALL poder ajustar la confianza base solo dentro de un delta acotado y siempre
con una justificación explícita del ajuste.

#### Scenario: Confianza ajustada
- **WHEN** el arbitraje modifica la confianza base
- **THEN** el sistema registra la confianza base, la confianza final y la
  justificación del delta

#### Scenario: Confianza sin ajuste
- **WHEN** el arbitraje no modifica la confianza base
- **THEN** el sistema registra que no hubo ajuste y no inventa justificación

#### Scenario: Conflicto de políticas
- **WHEN** una transacción satisface dos políticas con acciones distintas
- **THEN** gana la más restrictiva según la precedencia `BLOCK >
  ESCALATE_TO_HUMAN > CHALLENGE > APPROVE`

### Requirement: Explicabilidad en lenguaje natural
El sistema SHALL producir dos explicaciones por caso: una dirigida al cliente y
una de auditoría, fundamentadas en las señales, citas y decisiones del caso.

#### Scenario: Explicación de auditoría trazable
- **WHEN** se solicita la explicación de auditoría de un caso decidido
- **THEN** el sistema la produce referenciando las señales, citas internas y
  externas y el veredicto emitido

### Requirement: Degradación de agentes con LLM
Un fallo en un agente con LLM SHALL degradar la decisión registrando el agente
fallido y el detalle del error, y SHALL NO abortar el análisis del caso.

#### Scenario: Agente de inteligencia externa falla
- **WHEN** la consulta a fuentes externas falla
- **THEN** el sistema continúa el análisis, registra el agente como degradado y el
  resultado refleja que faltó esa evidencia

### Requirement: Salida estructurada de los agentes con LLM
Cada agente con LLM SHALL devolver un objeto estructurado conforme al esquema de
su responsabilidad, de modo que el resto del grafo y el evaluador puedan consumir
su salida sin interpretación libre.

#### Scenario: Salida inválida del modelo
- **WHEN** el modelo devuelve una salida que no se ajusta al esquema esperado
- **THEN** el sistema lo trata como fallo del agente y degrada en lugar de
  introducir el texto crudo en el estado
