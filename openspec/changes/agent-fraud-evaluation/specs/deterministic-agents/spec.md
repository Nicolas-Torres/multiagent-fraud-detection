## Purpose

Define el comportamiento de los agentes de lógica pura del grafo de fraude:
cómo evalúan las políticas del catálogo contra transacción, perfil e historial y
cómo componen el riesgo determinístico que respalda el veredicto.

## ADDED Requirements

### Requirement: Evaluación determinística de políticas
El sistema SHALL evaluar las políticas del catálogo vigente (FP-01…FP-11, sin
FP-10) mediante lógica determinística sobre la transacción bajo análisis, el
perfil de comportamiento del cliente y su historial reciente, y SHALL producir
una señal por cada política que se cumpla.

#### Scenario: Monto y horario fuera de rango
- **WHEN** una transacción supera 3 veces el promedio habitual del cliente y su
  hora local cae fuera de la ventana habitual
- **THEN** el sistema produce la señal de la política correspondiente con
  severidad `medium`

#### Scenario: Cliente sin perfil
- **WHEN** una transacción proviene de un cliente sin perfil de comportamiento
  registrado
- **THEN** el sistema produce la señal `NO_CUSTOMER_PROFILE` y evalúa únicamente
  las políticas que no dependen del historial de comportamiento

#### Scenario: Política sin evidencia reproducible
- **WHEN** una política depende de búsqueda web externa no reproducible
- **THEN** el sistema no la evalúa ni la considera en la decisión

### Requirement: Invariante temporal as-of
Toda consulta de historial SHALL estar acotada por el timestamp de la transacción
bajo análisis (`timestamp <= as_of`), nunca por el instante actual, y SHALL incluir
a la propia transacción en su ventana.

#### Scenario: Ráfaga incompleta al momento del análisis
- **WHEN** una transacción ocurre antes de que existan las transacciones que
  completan un patrón multi-transacción
- **THEN** el sistema evalúa solo lo que existía en ese instante y no dispara la
  política por ver el futuro

#### Scenario: Historial cruzando cuentas en un dispositivo
- **WHEN** el sistema consulta el historial de un dispositivo
- **THEN** no filtra por cliente, porque un dispositivo usado con varias cuentas
  es la señal que busca

### Requirement: Semántica de zona horaria y moneda
El sistema SHALL evaluar la ventana horaria en la hora local del cliente definida
por su zona IANA (nunca UTC ni un supuesto global) y SHALL comparar montos solo
dentro de la misma moneda de la cuenta, aplicando los umbrales monetarios en la
moneda de referencia de la cuenta.

#### Scenario: Ventana nocturna cruzando la medianoche
- **WHEN** el perfil del cliente define una ventana habitual que cruza la
  medianoche (por ejemplo 22–06)
- **THEN** el sistema considera dentro de rango las horas de ambos tramos

#### Scenario: Comparación multi-moneda
- **WHEN** la transacción ocurre en un país distinto del de la cuenta
- **THEN** el monto se compara contra el promedio de la cuenta usando la moneda de
  la cuenta, no la del país de compra

### Requirement: Determinismo de las señales
Para una misma transacción, perfil e historial, el sistema SHALL producir el mismo
conjunto y orden de señales en corridas repetidas.

#### Scenario: Mismo caso, misma salida
- **WHEN** el mismo caso se evalúa dos veces con la misma evidencia
- **THEN** ambas corridas producen señales idénticas en código, descripción,
  severidad y orden

#### Scenario: Orden estable entre ramas paralelas
- **WHEN** varios agentes de un mismo superstep emiten señales
- **THEN** el sistema aplica un criterio de orden determinístico y documentado a
  la lista agregada de señales

### Requirement: Composición de riesgo y confianza base
El sistema SHALL calcular un `risk_score` (sospecha) monotónico en las severidades
de las señales y una `base_confidence` (seguridad) con forma de U: máxima ante
señales nulas o contundentes y mínima ante señales contradictorias o evidencia
incompleta. El `risk_score` SHALL NO ser ajustable por agentes con LLM.

#### Scenario: Evidencia incompleta
- **WHEN** un agente de evidencia falla y el caso se analiza degradado
- **THEN** la `base_confidence` baja sin que el `risk_score` cambie

#### Scenario: Señales contradictorias
- **WHEN** existen señales graves a favor y en contra de fraude
- **THEN** el `risk_score` refleja la severidad acumulada y la `base_confidence`
  baja por la contradicción

### Requirement: Deduplicación de señales
El sistema SHALL deduplicar señales redundantes producidas por más de un agente
antes de persistirlas, conservando la información del emisor para la atribución de
falsos positivos.

#### Scenario: Señal redundante
- **WHEN** dos agentes emiten la misma señal sobre la misma condición
- **THEN** el sistema persiste una sola instancia de la señal
