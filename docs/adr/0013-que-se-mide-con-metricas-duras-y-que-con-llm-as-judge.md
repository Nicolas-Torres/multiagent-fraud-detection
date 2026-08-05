# ADR-0013: qué se mide con métricas duras y qué con LLM-as-judge

- **Estado**: aceptado
- **Fecha**: 2026-08-04

## Contexto

Hasta ahora la evaluación de este proyecto no necesitó herramienta.
`check_policies.py` compara dos implementaciones independientes sobre 7 000 filas
y devuelve código distinto de cero; `validate_dataset.py` hace lo mismo con los
invariantes del dataset. Alcanza mientras todo lo medido tiene **respuesta
correcta**.

[ADR-0011](0011-citacion-por-identidad-descubrimiento-por-similitud.md) y
[ADR-0012](0012-el-indice-vectorial-es-dato-derivado-y-versionado.md) cierran el
RAG. Detrás vienen seis nodos con LLM —Threat Intel, los dos debates, el Arbiter y
Explainability— cuya salida es texto libre y no admite comparación exacta. Es la
primera vez que el proyecto tiene que medir algo que **no tiene respuesta
correcta**, y el entregable 6 pide métricas de producción mientras el 7 pide
métricas de calidad.

La pregunta llegó formulada como *"¿RAGAS, DeepEval o Langfuse?"*, y comparadas de
frente son un error de categoría: Langfuse es una plataforma de observabilidad,
RAGAS una biblioteca de métricas para RAG **generativo**, DeepEval un framework de
tests. La pregunta útil no es cuál es mejor sino **qué capa ocuparía cada una y si
esa capa está vacía**.

Y hay una restricción previa que ordena todo, porque
[ADR-0005](0005-exclusion-de-fp-10-por-evidencia-no-reproducible.md) y
[ADR-0006](0006-reparto-deterministico-y-llm.md) ya la fijaron: el harness mide
algo estable, o no mide nada.

## Decisión

El reparto se corta **por la misma costura que ADR-0006 cortó el sistema**:

> **Donde hay respuesta correcta, se compara. Donde no la hay, se juzga — y el
> juicio se declara como tal.**

Un LLM-as-judge aplicado a algo que tiene respuesta exacta no es una métrica más
blanda: es cambiar una verdad por una estimación, y pagar por el cambio.

| Capa | Qué mide | Con qué | Determinismo |
|---|---|---|---|
| **Observabilidad** | trazas, latencia, costo, ruta de agentes | **LangSmith** | n/a |
| **Reglas y recuperación** | catálogo contra ground truth · recall@k y MRR contra `expected_policies` | **código propio** (numpy + pytest) | total |
| **Juicio** | Arbiter, debates, explicaciones | **DeepEval** | acotado y declarado |

### 1. Observabilidad: LangSmith, que ya estaba decidida

El contrato §1.4 declara `LANGSMITH_API_KEY`, `LANGSMITH_TRACING` y
`LANGSMITH_PROJECT` como variables del contrato operativo. No es decisión nueva;
se registra acá porque es la razón por la que la capa está ocupada.

### 2. Recuperación: código propio, no una biblioteca

El ground truth de este sistema **no es texto**. `expected_policies` es un
conjunto etiquetado de identificadores de documento por transacción, sobre 7 000
filas. Eso es ground truth de *information retrieval* clásico, y su métrica es
**recall@k, MRR y hit-rate**: treinta líneas de numpy, determinista, sin costo,
offline gracias a ADR-0012, y con la misma convención de código de salida que los
dos gates que ya existen.

Es la métrica que ADR-0011 dejó definida como ablación de el bloque semántica.

### 3. Juicio: DeepEval

Tres razones que son de este proyecto y no genéricas:

- **Está construido sobre pytest.** Los 111 tests no se mudan de runner, el CI no
  aprende un comando nuevo, y `deepeval test run` devuelve código distinto de cero
  al fallar — la misma convención de `check_policies.py`.
- **`BaseMetric` y las métricas DAG permiten scoring determinístico.** *"La
  explicación de auditoría nombra todas las políticas de `matched_policies`"* es
  verificable sin LLM. G-Eval queda reservado para lo que de verdad requiere
  juicio, en vez de ser el default.
- **Tiene `flaky=True`.** Suena menor y decide: es la herramienta admitiendo que
  un umbral de LLM oscila entre corridas. Deja marcar explícitamente qué es no
  determinista, en lugar de fingir que nada lo es — que es la postura que ADR-0005
  y ADR-0006 vienen sosteniendo por escrito.

### 4. Ninguna métrica de juicio bloquea un merge

Los gates de CI que fallan un build son **solo los determinísticos**. Las métricas
de LLM-as-judge se reportan y se vigilan por tendencia sobre un *golden set*
curado, no sobre las 7 000.

Es la consecuencia directa de la regla: un gate cuyo veredicto oscila entre
corridas no separa código bueno de código malo, separa corridas de corridas. Y un
equipo que ve fallar un build por ruido aprende a reintentar hasta que pase, que
es la forma más cara de no tener gate.

### 5. Lo que sigue sin medirse con F1

**External Threat Intel**, por ADR-0005: su evidencia no es reproducible y su
aporte se evalúa cualitativamente. Esta decisión no lo cambia; lo reafirma.

## Alternativas descartadas

**RAGAS.** Es la biblioteca más profunda en métricas específicas de RAG, es
*reference-free*, y es exactamente el nombre que alguien espera encontrar en un
proyecto cuyo entregable central es un RAG — su ausencia va a generar la pregunta,
así que la respuesta va escrita. Se descarta por dos razones independientes:

- **Sus métricas insignia presuponen un RAG generativo.** *Faithfulness* y *answer
  relevancy* puntúan una **respuesta generada** contra el contexto recuperado.
  Este RAG no genera respuesta: recupera políticas que alimentan al Arbiter dos
  supersteps después. Habría que inventar un `answer` únicamente para poder
  puntuarlo.
- **Sus métricas de contexto las juzga un LLM.** *Context precision* y *context
  recall* son juicios de un modelo sobre si el contexto era relevante. Ponerlas en
  el gate mete por la puerta de la métrica el no determinismo que ADR-0006 cerró
  por la puerta del motor.

Y un tercer punto que remata: `context_recall` le pagaría a un LLM para estimar,
de forma aproximada, un juicio de relevancia que `expected_policies` **ya afirma
exactamente sobre 7 000 filas**. Es cambiar etiquetas duras por etiquetas blandas
y pagar por el cambio.

> No queda descartada para siempre. El día que el RAG genere una síntesis en
> lenguaje natural sobre las políticas recuperadas, *faithfulness* recupera su
> sujeto y la decisión se revisa.

**Langfuse.** Open source, self-hosteable, con buen manejo de datasets y anotación
humana; el patrón que suele recomendarse —trazas en Langfuse, un job muestreando
un porcentaje y escribiendo scores de vuelta— es sólido y está bien probado. Se
descarta porque **la capa que ocuparía ya está ocupada**: adoptarla significa dos
backends de trazas y dos dashboards, y —lo que decide— un servicio nuevo que
aterriza del lado de infraestructura, que valida el compañero. Es una enmienda al
contrato operativo a cambio de nada que LangSmith no dé hoy.

**DeepEval también para la recuperación**, con sus métricas contextuales. Sería
una herramienta menos y una capa menos que explicar. Se descarta porque esas
métricas también son LLM-as-judge: heredarían el defecto de RAGAS sin heredar su
profundidad. **La herramienta se adopta por la capa que ocupa, no por el tamaño de
su catálogo.**

**Ninguna herramienta: asserts propios también para el juicio.** Es la postura que
el proyecto viene sosteniendo, y funcionó hasta acá. Se descarta porque escribir
un juez propio —prompt, parseo de la salida, umbral, manejo de la oscilación— es
reimplementar DeepEval peor, y sin sus dos aportes reales: vivir dentro de pytest
y nombrar lo *flaky*.

**LangSmith también para los gates**, aprovechando que ya está. Se descarta por
una decisión de frontera, no de capacidad: los gates de este proyecto corren
**offline y herméticos** —es lo que hace que `check_policies.py` valga un segundo y
no dependa de nadie—. Un gate que consulta un servicio externo falla cuando el
servicio falla. LangSmith observa; no bloquea un merge.

## Consecuencias

**Se gana un reparto que no agrega vocabulario**: la evaluación se corta por la
misma costura que el sistema —sensores contra juicio—, así que el argumento de
ADR-0006 se reusa entero y el informe tiene una sola idea que explicar en vez de
dos.

**Se gana que todo gate que bloquea un merge sea determinístico y offline.** El
único componente no determinista de la suite queda marcado como tal, en vez de
disuelto entre los demás.

**Se gana material para la rúbrica.** El entregable 7 pide comparación de
enfoques; tener dos regímenes de medición explicados —y explicado por qué la
herramienta obvia no está— es contenido de informe, no relleno.

**Se paga:**

- **Dos herramientas donde alguien esperaría una**, y la ausencia de RAGAS hay que
  defenderla activamente. Mismo riesgo de rúbrica que ADR-0006 registró: bien
  argumentado suma, no argumentado parece desconocimiento.
- **DeepEval trae su propia dependencia de LLM juez**, con costo y cuota. Se acota
  corriendo sobre un *golden set* curado y no sobre las 7 000.
- **El juez puede equivocarse, y la mitigación no es más juez.** Es la decisión 4:
  ninguna métrica de juicio bloquea un merge; se reportan y se vigilan por
  tendencia.
- **El *golden set* no existe todavía** y curarlo a mano es trabajo nuevo. Queda
  declarado como deuda de la etapa de agentes con LLM, no de ésta.

**Extiende ADR-0006** de la arquitectura a su medición, **reafirma ADR-0005** en
que External Threat Intel no se mide con F1, y **le da lugar a la ablación de
ADR-0011**: capa 2, gate duro, sin herramienta.
