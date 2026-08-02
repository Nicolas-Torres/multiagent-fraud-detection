# ADR-0006: qué nodos usan LLM y cuáles son determinísticos

- **Estado**: aceptado
- **Fecha**: 2026-08-02

## Contexto

El reto enumera ocho agentes y exige "un equipo multi-agente orquestado". El grafo
implementado tiene diez nodos —los ocho del reto, más un segundo agente de debate
y el persistidor—.

La palabra *agente* significa dos cosas distintas que hoy se confunden:

- **En orquestación** (LangGraph): un nodo con responsabilidad propia, acceso al
  estado y fallo independiente. No implica LLM.
- **En el uso corriente**: una entidad que razona, elige herramientas e itera.
  Implica LLM.

El reto usa el término sin definirlo, y su propio ejemplo de flujo describe al
Transaction Context Agent como algo que *"detecta monto y horario fuera de lo
habitual"* — una comparación aritmética.

El reparto venía dándose por hecho desde la etapa del grafo, pero **existía solo
como dos filas de la tabla de estado del README**, sin argumento en ninguna parte.
Este ADR lo registra o lo corrige.

## Decisión

El criterio que ordena el reparto:

> **Los nodos determinísticos son los sensores; los nodos con LLM son el juicio.**
> Un sensor debe ser confiable y reproducible. El juicio es donde vive la
> ambigüedad.

| Nodo | Motor | Por qué |
|---|---|---|
| Transaction Context | determinístico | compara umbrales explícitos del catálogo |
| Behavioral Pattern | determinístico | contrasta contra perfil e historial |
| Evidence Aggregation | determinístico | fusiona señales y compone `risk_score` |
| Internal Policy RAG | **LLM** | recuperación semántica y síntesis de política |
| External Threat Intel | **LLM** | leer web no estructurada |
| Debate Pro-Fraude | **LLM** | construir el argumento acusatorio |
| Debate Pro-Cliente | **LLM** | construir el descargo |
| Decision Arbiter | **LLM** | juicio bajo evidencia contradictoria |
| Explainability | **LLM** | lenguaje natural para cliente y auditoría |
| Persistencia | — | no es agente: es la costura con la base |

Seis de los nueve agentes usan LLM.

Tres razones sostienen el lado determinístico:

**Las políticas son reglas con umbrales explícitos.** FP-01 dice "monto > 3× el
promedio y horario fuera de rango". Preguntarle a un LLM si 4 500 > 3 600 usa la
herramienta menos confiable disponible para la operación más simple, y se equivoca
sin avisar.

**Auditabilidad.** Una decisión de fraude se explica a un regulador. *"FP-01
disparó porque 4 500 > 3 600 y las 03:15 caen fuera de 08–20"* es auditable; *"el
modelo consideró que el monto era inusual"* no. El contrato ya sostenía esta
postura para `risk_score`: **no es ajustable por el Arbiter, precisamente para que
un LLM no pueda moverlo.**

**Reproducibilidad del harness.** Si Context fuera un LLM, la misma transacción
produciría señales distintas entre corridas y el F1 sería ruido. Es el mismo
argumento que dejó a FP-10 fuera de alcance ([ADR-0005](0005-exclusion-de-fp-10-por-evidencia-no-reproducible.md)).

**Complemento**: Transaction Context se implementa **de las dos formas** y se
miden ambas contra el mismo ground truth. La rúbrica del entregable 7 pide
"comparación de enfoques" y hoy no había ninguna planeada; ésta es la más barata
posible —mismo grafo, mismo dataset, mismo harness, un nodo intercambiado— y el
resultado sirve en cualquier dirección.

## Alternativas descartadas

**Todo con LLM, los nueve agentes.** Es la lectura literal de "agente" en su
sentido corriente y la que menos explicaciones pide. Se descartó porque
introduciría no determinismo en la capa que el harness mide, haría inauditable la
evidencia y gastaría llamadas caras en comparaciones aritméticas. El sistema sería
más impresionante de describir y peor de evaluar.

**Todo determinístico.** Técnicamente posible: las diez políticas son reglas, y un
motor de reglas las cubre. Se descartó porque tira lo que el reto pide —debate,
arbitraje sobre evidencia contradictoria, explicación en lenguaje natural,
recuperación semántica de políticas— y porque hay ambigüedad real que una regla no
resuelve: cuando FP-02 dice escalar y el historial del cliente es impecable,
alguien tiene que ponderar.

**Los nodos determinísticos como *tools* que invoca un agente LLM.** Es el patrón
agéntico canónico: un LLM decide qué comprobación aplicar y llama a la función.
Se descartó porque agrega no determinismo en *qué se comprueba* sin agregar
juicio: el catálogo ya define exactamente qué políticas aplican a qué
transacción. La elección que el LLM haría es una elección que no hay que hacer.

**Behavioral Pattern con LLM.** Es el caso más discutible de los tres —"comparar
con el historial" admite lecturas más ricas que contrastar umbrales, como
reconocer que un patrón parece un familiar usando la tarjeta—. Se descartó por
falta de sustento: no hay ground truth para esos matices, así que la mejora sería
indemostrable. Es el primer candidato a revisar si aparece evidencia.

## Consecuencias

**Se gana** un harness que mide algo estable, evidencia auditable línea por línea,
y latencia y costo acotados: seis llamadas a LLM por caso en vez de nueve.

**Se paga** que el sistema es menos "agéntico" de lo que la etiqueta sugiere. Tres
de los nueve agentes son funciones puras con una firma de nodo. Quien cuente LLMs
va a objetar, y **el argumento tiene que estar explícito en el informe**, no
implícito en el código. Argumentado, suma en la rúbrica; no argumentado, resta.

**El reparto no es simétrico y eso es deliberado.** Los sensores son baratos,
rápidos y corren en paralelo; el juicio es caro y secuencial. Esa asimetría es
también la razón por la que `@degrades` vive en los nodos de evidencia: son los
que pueden fallar sin que el caso se caiga.

**Queda una comparación pendiente de ejecutar** (Context determinístico vs. con
LLM). Si el LLM ganara en algún subconjunto, este ADR se revisa. Registrarlo como
promesa y no cumplirlo sería peor que no haberlo prometido.
