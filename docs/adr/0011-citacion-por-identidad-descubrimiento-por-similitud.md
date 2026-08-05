# ADR-0011: la citación se resuelve por identidad y el descubrimiento por similitud

- **Estado**: aceptado
- **Fecha**: 2026-08-04

## Contexto

[ADR-0007](0007-la-forma-ejecutable-de-una-politica-es-una-vinculacion.md) fijó que
el documento normativo es el corpus del RAG y que la vinculación es su forma
ejecutable. No fijó **de dónde sale `citations_internal`**, y ese hueco tiene la
misma forma que el que aquel ADR vino a cerrar.

El contrato §2.5 establece el invariante que gobierna todo veredicto autónomo:

> Cuando `decision != ESCALATE_TO_HUMAN`, `citations_internal` es no vacío **y**
> `base_confidence` no es `null`.

Hoy no hay RAG, así que todo caso escala y el invariante es una promesa que
ningún caso ejercita. Con el nodo `internal_policy_rag` en producción empieza a
ejercitarse en las 7 000, y ahí importa de dónde salieron esas citas.

La lectura natural —y la que el nombre del nodo sugiere— es que el RAG recupera
por similitud y lo recuperado *son* las citas. Tiene un defecto que el propio
ADR-0007 ya nombró, aunque contra otra alternativa:

> La recuperación semántica es **aproximada por diseño**. Una política puede no
> aplicarse **porque no fue recuperada**, y ese fallo es silencioso —no hay
> excepción, no hay log, solo una transacción aprobada—.

Trasladado a la citación, el escenario es peor. El motor dispara FP-03; el índice
devuelve FP-05, FP-02 y FP-08, que hablan de lo mismo con otras palabras. El caso
se decide `BLOCK` —correctamente, porque la decisión sale del motor— y **cita tres
normas que no aplicó**. Nada falla: no hay excepción, el invariante se cumple
porque la lista no está vacía, y el auditor recibe una explicación coherente y
falsa.

Es un modo de fallo más grave que el que ADR-0007 cerró. Allá la divergencia era
entre el texto y el umbral, y la huella criptográfica la detecta. Acá la
divergencia es entre **la norma aplicada y la norma citada**, y no hay huella que
la detecte: ambos artefactos están intactos y verificados. Lo que falló fue el
emparejamiento entre ellos, que ningún hash cubre.

El invariante, tal como está redactado, lo esconde: pide que la lista sea **no
vacía**, no que sea **correcta**. Una lista con las citas equivocadas lo
satisface.

## Decisión

`citations_internal` tiene **dos orígenes con garantías distintas**, y lo que se
persiste es su unión.

| Pierna | Cómo se resuelve | Qué aporta | Garantía |
|---|---|---|---|
| **Autorización** | lookup por `policy_id` de cada elemento de `matched_policies` | toda política que disparó completa | **total**: no depende del índice ni del modelo |
| **Descubrimiento** | búsqueda vectorial con la query armada desde los códigos de señal | políticas relacionadas que **no** dispararon | **ninguna**: es aproximada por diseño |

El invariante estructural que se hace cumplir en el nodo:

```
citations_internal  ⊇  { documento(p) : p ∈ matched_policies }
```

Es un `assert`, no una métrica. Se cumple por construcción y su violación es un
defecto, no un resultado — mismo criterio que las tres guardas de W2 (§7.3), que
**levantan y no reparan**.

**La distinción entre ambas piernas no se modela.** El Arbiter necesita saber qué
política disparó y cuál solo se parece, y el contrato ya se lo dice: `Decision`
expone `matched_policies` y `citations_internal` como campos separados, y la
intersección es una operación de conjuntos. Agregarle un `retrieved_by` a
`InternalCitation` sería modelar lo que se puede derivar (§7.2), y ampliaría la
frontera pública sin necesidad.

La discrepancia entre las dos listas **es el aporte del nodo**, no su error: una
política recuperada y no disparada es evidencia de que algo se parece a un patrón
conocido sin cumplirlo, y eso es exactamente lo que un Arbiter debe ponderar.

## Alternativas descartadas

**Solo similitud.** Es la lectura natural de "RAG", deja el índice como única
fuente, no tiene caso especial, y con once documentos y un buen modelo va a
acertar casi siempre. Se descarta porque *"casi siempre"* no es una garantía y el
fallo es silencioso: la tasa de acierto no es una propiedad del diseño sino del
modelo, que se actualiza del lado del proveedor sin avisar. Además convierte una
caída del servicio de embeddings en el escalamiento del lote entero — el nodo
lleva `@degrades`, y sin autorización determinística degradar significa quedarse
sin citas y por lo tanto sin veredicto autónomo posible.

**Solo identidad.** Cumple el invariante, es determinista y no necesita índice.
Se descarta porque tira justo lo que el RAG aporta: FP-10 tiene documento y no
tiene vinculación, así que por identidad es **inalcanzable** —el motor nunca la
dispara— y solo la similitud puede citarla. Y el sistema perdería la política que
no disparó y sin embargo importa, que el acta 05 §9.4 identifica como evidencia
para el Arbiter.

**Similitud con verificación posterior**: recuperar por índice y fallar si alguna
política disparada no aparece. Mantiene una sola pierna y el fallo deja de ser
silencioso. Se descarta porque convierte una recuperación incompleta en un caso
`FAILED` cuando la información para citar bien estaba disponible **sin consultar
el índice**. Es construir la detección de un problema que se podía no tener.

**Subir el umbral de similitud** para que solo entren las políticas realmente
relevantes. Se descarta porque muda el problema a un número sin ground truth, que
hay que recalibrar cada vez que cambia el modelo de embeddings, y que sigue sin
garantizar nada: un umbral alto reduce las citas espurias y aumenta las
ausencias, que es el lado caro del error.

**Reranker sobre el resultado del índice.** Sube el recall efectivo y es una
mejora legítima. No se descarta como mejora de la **pierna de descubrimiento**;
se descarta como sustituto de la de autorización, porque sube la probabilidad y
no la garantía, y agrega una llamada más al camino crítico.

## Consecuencias

**Se gana** que el invariante de §2.5 pase de promesa a propiedad estructural,
verificable con un `assert` en el nodo y no con una métrica que se mira después.

**Se gana la simetría con ADR-0007**, y es lo que cierra el ciclo: la huella
impide **aplicar un umbral distinto del que se cita**; esta decisión impide
**citar una norma distinta de la que se aplicó**. Las dos juntas hacen que texto y
ejecución no puedan divergir en ninguna de las dos direcciones.

**Se gana degradación proporcionada.** Si el proveedor de embeddings se cae,
`@degrades` deja el caso sin descubrimiento pero con autorización: el veredicto
sobrevive, la confianza baja, y `degraded_agents` lo dice. Una falla de
infraestructura de terceros deja de ser una falla de cumplimiento.

**Se contesta la pregunta 3 del acta 05** —*cómo medir la recuperación si el
ground truth habla de políticas disparadas y no de políticas recuperadas*—
disolviéndola. `expected_policies` no es un proxy pobre del conjunto relevante:
es la respuesta exacta a *qué citas son obligatorias*, y no dice nada sobre cuáles
están permitidas. Define recall con precisión total y precision en absoluto. Como
la pierna de autorización tiene recall 1.0 por construcción, el ground truth pasa
a medir una **ablación de la pierna semántica**, no un gate.

**Se paga:**

- **El nodo tiene dos caminos** y los dos necesitan prueba, incluido el caso en
  que ambas piernas devuelven el mismo documento y hay que deduplicar por
  `chunk_id`.
- **La ablación va a producir un número incómodo y hay que publicarlo.** Si la
  pierna semántica sola recupera el 93% de las políticas disparadas, ese 7% es la
  proporción de veredictos autónomos que habrían citado mal. Es la evidencia
  empírica de este ADR; leído fuera de contexto parece una métrica de un sistema
  que no funciona.
- **Hay una objeción previsible** —*"entonces el RAG no decide nada"*— que **tiene
  que estar contestada en el informe**, no implícita en el código: la pierna de
  descubrimiento alimenta al Arbiter, FP-10 solo es alcanzable por ella, y con
  circulares y manuales reales en vez de once líneas es la que hace el trabajo,
  mientras la de identidad sigue siendo un lookup. Mismo riesgo de rúbrica que
  ADR-0006 registró para el reparto determinístico: argumentado suma, no
  argumentado resta.
- **El corpus de once líneas sobredimensiona la pierna de identidad.** Es una
  limitación del dataset y no del diseño, y va declarada como tal.

**No toca ADR-0006**: el nodo sigue del lado del LLM —la recuperación semántica y
la síntesis siguen siendo suyas— y el argumento sale reforzado, porque ahora la
parte del nodo que el invariante depende de es determinística y la parte que
juzga no lo es, que es exactamente el criterio *sensores contra juicio*.

**Extiende ADR-0007** sin contradecirlo: aquel decidió que la forma ejecutable de
una política es una vinculación al documento; éste decide que la forma **citable**
de una política aplicada es el documento del que se derivó, alcanzado por
identidad y no por parecido.
