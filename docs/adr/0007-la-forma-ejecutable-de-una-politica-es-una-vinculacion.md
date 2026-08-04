# ADR-0007: la forma ejecutable de una política es una vinculación al documento normativo

- **Estado**: aceptado
- **Fecha**: 2026-08-03

## Contexto

[ADR-0006](0006-reparto-deterministico-y-llm.md) fijó **qué motor** usa cada nodo:
Transaction Context, Behavioral Pattern y Evidence Aggregation son determinísticos
porque las políticas son reglas con umbrales explícitos. No fijó **dónde viven
esas reglas**, y ese hueco resultó tener consecuencias.

El plan inicial traducía las once políticas a funciones de Python en
`domain/policies.py`. Dos defectos que no se ven hasta proyectar el sistema más
allá de la entrega:

**El autor de una política no es un ingeniero.** Es un oficial de cumplimiento del
banco que reacciona a un patrón que apareció el martes. Con reglas como código,
cada umbral ajustado y cada política nueva son un commit, un build y un
despliegue. Ese ciclo es la ventana en la que el fraude opera.

**El texto y el umbral pueden divergir en silencio.** Si el banco edita FP-01 de
"3×" a "4×", el RAG cita el texto nuevo y el motor sigue disparando con 3. El
sistema le explica al auditor una regla distinta de la que aplicó, y nada falla.

Hay además una restricción de propiedad que el plan inicial ignoraba: **el
catálogo de políticas es un documento del banco.** Cualquier diseño que requiera
agregarle campos —aunque sea para nuestro propio motor— le atribuye al banco
decisiones que no tomó.

La restricción que ordena todo esto ya estaba aceptada: si la evaluación es
determinística, **alguien tiene que traducir la prosa a una comparación exacta**.
Eso es cierto tanto con reglas como código como con reglas como dato. Este ADR no
crea ese trabajo: lo saca del código y lo pone donde se ve.

## Decisión

Una política vive como **tres artefactos con tres dueños**:

| Artefacto | Dueño | Qué es | Quién lo consume |
|---|---|---|---|
| **Documento normativo** | el banco | prosa con autoridad, versionada | Internal Policy RAG (chunk + embed) |
| **Vinculación** | nosotros | la traducción ejecutable de ese documento | el intérprete determinístico |
| **Biblioteca de predicados** | código | catorce operaciones cerradas y parametrizables | la vinculación las referencia |

El documento **no se toca**: llega en su formato y se trata como insumo externo.
La vinculación es un registro propio que declara de qué documento se derivó, con
qué predicados y parámetros, quién la escribió y cuándo, más una **huella
criptográfica del texto que tradujo**. Al cargar, el sistema recalcula la huella
del documento vigente: si no coincide, la traducción es de un texto que ya no
existe.

De ahí salen cuatro estados legítimos:

| Estado | Cuándo | RAG | Motor |
|---|---|---|---|
| **Activa** | vinculación con huella vigente | cita | evalúa |
| **Excluida** | vinculación con `condition: null` y motivo registrado | cita | no evalúa |
| **Pendiente** | documento sin vinculación | cita | no evalúa |
| **Obsoleta** | la huella dejó de coincidir | cita el texto **nuevo** | no evalúa |

*Excluida* y *pendiente* se separan a propósito: FP-10 no está traducida **por
decisión** ([ADR-0005](0005-exclusion-de-fp-10-por-evidencia-no-reproducible.md)),
no por falta de tiempo. Sin esa distinción, la métrica de políticas sin traducir
marcaría 1 para siempre y sería ruido.

Ante una vinculación obsoleta el sistema **degrada**: la política deja de
evaluarse, sigue siendo citable, y la anomalía se registra. Es coherente con la
decisión 12 del contrato —*la falla de un agente degrada la decisión, no la
aborta*— y evita que una edición del banco deje el motor fuera de servicio.

Consecuencia estructural: **cada predicado emite una señal atómica y cada política
es la conjunción de sus predicados**. La frontera entre `signals` —lo que el
sistema mide— y `expected_policies` —el vocabulario del ground truth— deja de ser
una convención por acordar.

Detalle en [`catalogo_de_politicas.md`](../catalogo_de_politicas.md).

## Alternativas descartadas

**Políticas como funciones de Python (*rules as code*).** Es el plan original y un
patrón legítimo: da revisión por pares, tests, historial y rollback gratis. Se
descarta porque el criterio que decide no es técnico sino **quién escribe la
regla**: si es un ingeniero, código está bien; si es cumplimiento, tiene que ser
dato. Acá es lo segundo.

**Enriquecer el documento del banco con campos ejecutables.** Fue la primera
corrección propuesta —meter `condition` y `action` en el mismo JSON, "una fila,
dos caras"—. Se descarta porque compra la garantía al precio de escribir dentro de
un artefacto ajeno: obligaría al personal de banca a conocer un vocabulario de
predicados que no es suyo. La garantía se conserva por huella, que no requiere
tocar el original.

**Políticas únicamente en la base vectorial, evaluadas por un LLM sobre el texto
recuperado.** Es la única alternativa que elimina la traducción por completo. Se
descarta por tres razones independientes:

- La recuperación semántica es **aproximada por diseño**. Una política puede no
  aplicarse **porque no fue recuperada**, y ese fallo es silencioso —no hay
  excepción, no hay log, solo una transacción aprobada—. En cumplimiento
  normativo, *"no la recuperamos"* no es una respuesta admisible.
- El índice vectorial es **dato derivado**: se reconstruye cada vez que cambia el
  modelo de embeddings. Un índice no puede ser la fuente de verdad de aquello que
  indexa.
- Rompe la reproducibilidad del harness, por el mismo argumento que dejó FP-10
  fuera de alcance (ADR-0005), y le pide a un LLM que decida si 4 500 > 3 600.

> No se descarta como **experimento**: en su forma extrema es el brazo con LLM de
> la comparación que ADR-0006 dejó prometida. Se mide sobre las 7 000.

**Vincular solo por `policy_id`, sin huella.** Más simple y suficiente mientras
nadie edite un documento. Se descarta porque la divergencia se vuelve
indetectable, que es el defecto que este ADR existe para cerrar.

**Un motor de reglas de propósito general (DSL o lenguaje embebido).** Las once
políticas se reducen a catorce predicados y a conjunciones de uno o dos: un
lenguaje completo compra expresividad que nadie pidió y cuesta un parser, un
sandbox y una superficie de fallo nueva.

**Fallar duro ante una vinculación obsoleta.** Más seguro en un banco real. Se
descarta porque le da a un editor externo la capacidad de dejar el motor fuera de
servicio con un cambio de redacción.

## Consecuencias

**El archivo de vinculaciones es un seed, no un flujo de trabajo.** Solo las
políticas que **llegan de afuera** necesitan traducción, y llegaron una vez: las
once del enunciado. Una política que nace en el dashboard captura texto y
condición en el mismo acto —no hay original al que amarrarse después—. Tras cargar
`policy_bindings_2025.1.json`, nadie vuelve a editar JSON a mano.

**El ciclo de gobernanza se cierra en el dashboard**, no en el repositorio: una
vista lista las políticas con su estado y un formulario captura las nuevas en dos
secciones —norma obligatoria, vinculación opcional—. Dejar la vinculación vacía es
un uso previsto, no un error: publica la norma hoy y la ejecuta cuando alguien la
componga.

**Se gana** que ajustar un umbral y agregar una política de forma conocida dejen de
necesitar despliegue; que el sistema no pueda aplicar un umbral distinto del que
cita; que el banco publique una política hoy y el sistema la cite hoy —antes, una
política que no estuviera en el código era invisible—; que el despacho *"cliente
sin perfil → solo son evaluables las políticas que no dependen del historial"* se
derive de los insumos declarados; y que FP-10 se represente sin caso especial.

**Se paga**, y conviene tenerlo escrito:

- **La frontera se mueve, no desaparece.** Una política con una forma que la
  biblioteca no cubre sigue necesitando código y despliegue.
- **La validación se corre de tiempo de compilación a tiempo de carga.** Obliga a
  validación de esquema y a un gate de CI que evalúe el catálogo completo contra el
  ground truth. Es el precio de la agilidad, no un extra opcional.
- **Aparece un modo de fallo nuevo**: la política vinculada a un texto muerto. Dos
  métricas operativas para el entregable 6: *políticas pendientes* y *vinculaciones
  obsoletas*.
- **La decisión tiene que sellar qué versión del catálogo evaluó.**
- **`chunk_id` de `InternalCitation` deja de ser hipotético**: en un caso real las
  políticas no son once líneas sino circulares y manuales que se chunkean.
- **La biblioteca de predicados debe ser introspectable** —parámetros como dato,
  no solo como firma de Python— para que el compositor del dashboard se arme solo.
- **Una vinculación nueva no tiene ground truth.** El validador atrapa errores de
  forma, no de semántica. El *shadow mode* contra tráfico histórico queda como
  deuda del entregable 10; sin él, la agilidad es una forma rápida de bloquear
  clientes legítimos.

**No toca ADR-0006 ni ADR-0005.** Un intérprete de condiciones estructuradas es
tan determinístico como un `if`, y los tres argumentos de ADR-0006 salen
reforzados: la evidencia auditable ahora incluye la versión y la huella exactas de
la norma evaluada, no solo su identificador.
