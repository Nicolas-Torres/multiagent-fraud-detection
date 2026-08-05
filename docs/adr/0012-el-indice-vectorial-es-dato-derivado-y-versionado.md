# ADR-0012: el índice vectorial es dato derivado, versionado y sellado en la decisión

- **Estado**: aceptado
- **Fecha**: 2026-08-04

## Contexto

pgvector está habilitado desde la primera migración (`c558fd490ae6`) y no se usó
nunca. [ADR-0011](0011-citacion-por-identidad-descubrimiento-por-similitud.md) le
da su primer consumidor: la pierna de descubrimiento del RAG de políticas.

[ADR-0007](0007-la-forma-ejecutable-de-una-politica-es-una-vinculacion.md) ya
había dicho, pero **contra una alternativa** y no como decisión propia:

> El índice vectorial es **dato derivado**: se reconstruye cada vez que cambia el
> modelo de embeddings. Un índice no puede ser la fuente de verdad de aquello que
> indexa.

Sirvió para descartar "políticas solo en la base vectorial". No dice nada sobre
cómo se construye el índice que sí va a existir, y ese hueco importa por un hecho
nuevo que esta etapa introduce.

**Hasta hoy todo lo que el harness mide se calcula dentro del proceso.** El
etiquetador, el intérprete, el scoring: dos implementaciones independientes que
coinciden en 7 000 filas, sin red. Un embedding no: llega por HTTP desde un
modelo que el proveedor puede actualizar del lado del servidor, sin aviso y sin
cambio de nombre. Si el harness llama a la API en cada corrida, la evidencia del
RAG tiene exactamente la forma que
[ADR-0005](0005-exclusion-de-fp-10-por-evidencia-no-reproducible.md) declaró no
evaluable:

> Una política cuya evidencia no es reproducible no es evaluable en un harness.

Y la ablación que ADR-0011 propone como única métrica del RAG —recall de la
pierna semántica contra `expected_policies`— sería la primera víctima: dos
corridas darían números distintos sin que nada haya cambiado en el repositorio.

Hay además tres restricciones concretas que empujan la forma de la solución:

- **pgvector no indexa columnas de más de 2000 dimensiones** con HNSW ni IVFFlat.
- El modelo vigente, `gemini-embedding-2`, produce **3072 dimensiones por
  defecto**, truncables por MRL a 1536 o 768.
- La recuperación es **asimétrica**: la query es una lista de códigos de señal, el
  documento es prosa normativa.

## Decisión

### 1. El índice se persiste; el harness lee de la base, nunca de la API

La indexación es un **acto explícito** (`scripts/index_policies.py`), idempotente,
que corre **dentro del Job de seed** —post-deploy, sin abortar el rollout
([ADR-0010](0010-seed-como-job-de-post-deploy.md))—. No es un cuarto modo de
arranque: la asimetría que justifica el seed vale igual acá, porque un índice sin
construir deja el descubrimiento vacío, no el servicio roto.

El grafo **nunca embebe el corpus**. Embebe solo la query, una llamada por caso.

Y esa llamada también se cachea, por una razón que viene de una decisión anterior:
**la query se arma desde los códigos de señal, no desde las `description`**. El
vocabulario de códigos es cerrado —catorce—, así que las queries distintas están
acotadas por las combinaciones observadas, órdenes de magnitud por debajo de las
7 000 transacciones. Con las `description`, que llevan montos, cada transacción
habría producido una query única y el caché no existiría. Aquella decisión paga
acá: tras la primera corrida, el harness completo es offline y determinista.

### 2. Parámetros del modelo

| Parámetro | Valor | Por qué |
|---|---|---|
| Modelo | `gemini-embedding-2` | **auto-normaliza las dimensiones truncadas**; `-001` obliga a normalizar a mano, y una normalización olvidada no falla: solo empeora el ranking en silencio |
| `output_dimensionality` | **1536** | por el techo de 2000 de pgvector, no por necesidad actual |
| `task_type` | `RETRIEVAL_DOCUMENT` al indexar · `RETRIEVAL_QUERY` al consultar | la recuperación es asimétrica; el mismo task_type en ambos lados degrada sin avisar |

La dimensión se elige **por el índice que todavía no hace falta**. Con once
documentos ningún ANN aporta, pero cambiar la dimensión más adelante obliga a
re-embeber el corpus entero, así que la decisión se toma una sola vez y se toma
mirando el caso real —circulares y manuales, no once líneas—.

### 3. El índice tiene versión, y la decisión la sella

`retrieval_index_version` es una columna nullable en `decisions`, junto a
`scoring_version` y `policy_catalog_version`, siguiendo el patrón ya establecido.

Versiona **los parámetros de derivación**, no el contenido del corpus:

| Qué cambia | ¿Sube `index_version`? | Quién lo registra si no |
|---|---|---|
| modelo, dimensión o `task_type` | **sí** | — |
| estrategia o parámetros de chunking | **sí** | — |
| texto de una política | no | `InternalCitation.version`, por cita |
| una vinculación | no | `policy_catalog_version` |

Con eso la auditoría se cierra en tres ejes independientes: **qué texto se citó**,
**qué traducción se evaluó** y **cómo se derivó el vector**.

El valor es una cadena **descriptiva**, `gemini-embedding-2:1536:doc:1`, y no un
identificador opaco: el motivo de sellarla es que alguien la lea dos años después
sin una tabla de consulta al lado. El último segmento sube por lo que los tres
primeros no muestran.

**El modelo no es variable de entorno.** Por la regla de §4 del contrato —*config
de infraestructura o dato de gobernanza*— un modelo configurable por `env` podría
cambiarse sin que suba la versión del índice, y entonces los tres sellos mentirían.
El modelo vive en código y queda registrado en cada fila de `policy_chunks`. Por
`env` viaja solo `GEMINI_API_KEY`, que ya está en §1.4.

### 4. Sin índice ANN por ahora

Once vectores se recorren exactos más rápido de lo que un HNSW los aproxima. Se
declara la ausencia y se documenta que agregarlo, con 1536 dimensiones, es una
migración de una línea que **no obliga a re-embeber**.

### 5. `chunk_id` no depende del modelo, y su redundancia se conserva

`{policy_id}:{version}:{ordinal}`. Re-embeber no cambia la identidad de las citas
ya persistidas: una decisión de enero sigue resolviendo su `chunk_id` contra el
índice reconstruido en marzo.

Que lleve `version` —la del **documento**— y no `index_version` es lo que compra
esa propiedad. Es también el motivo por el que la PK de `policy_chunks` es
`(index_version, chunk_id)` y no `chunk_id` solo: el mismo chunk existe una vez
por generación del índice, y eso es lo que hace idempotente la re-indexación.

**La redundancia se conserva.** `chunk_id` contiene `policy_id` y `version`, que
la tabla ya guarda en columnas propias y que `InternalCitation` ya expone como
hermanos. Se acepta la duplicación porque el identificador **viaja al auditor**:
un `chunk_id` legible se depura de un vistazo, y un id opaco obligaría a una
consulta para saber qué se citó — el mismo argumento que decide el formato de
`retrieval_index_version` en §3.

El precio es un invariante:

```
chunk_id == f"{policy_id}:{source_version}:{ordinal}"
```

Se afirma **en el chunker**, que es escritor único, y se cubre con un test. **No**
se afirma en el nodo de recuperación —sería una comprobación por consulta de algo
que ninguna ruta de escritura puede violar— ni con una columna generada o un
`CHECK`, que son punto ciego de `--autogenerate` y ya quedaron descartados dos
veces en el proyecto.

### 6. Los índices viejos no se podan, y por eso el filtro es obligatorio

No hay `--prune`. Con once documentos, las generaciones anteriores ocupan nada y
conservarlas permite comparar un índice nuevo contra el vigente antes de cambiar
de versión — que es justamente lo que la ablación de ADR-0011 va a querer hacer.

La contrapartida hay que escribirla porque no es obvia: si conviven generaciones,

> `WHERE index_version = <vigente>` deja de ser un filtro y pasa a ser un
> **invariante de corrección**.

Sin él, la búsqueda mezcla generaciones y devuelve vecinos calculados con un
modelo viejo. No falla, no lanza, no deja huella: devuelve resultados plausibles
y peores. Es la misma familia de fallo silencioso que ADR-0011 cierra del lado de
la citación y ADR-0007 del lado de la evaluación, y por eso el filtro vive en el
repositorio —una sola función de búsqueda, no un `where` que cada llamador
recuerda— y se cubre con un test que indexa dos generaciones y afirma que la
consulta sólo devuelve la vigente.

Cuál es la generación vigente lo dice el **código**, no una bandera en la tabla:
por la misma razón por la que el modelo no es variable de entorno, una bandera
mutable permitiría cambiar de índice sin que suba ningún sello.

## Alternativas descartadas

**Embeber en línea, sin persistir nada.** Con once documentos es viable —once
llamadas por caso— y tiene un atractivo real: cero dato derivado, cero
desincronización, el índice nunca queda viejo porque no existe. Se descarta
porque hace el harness dependiente de la red y de la versión del modelo del día,
multiplica las llamadas por caso, y no sobrevive a un corpus real. Sobre todo,
contradice ADR-0007 de frente: si el índice se reconstruye implícitamente en cada
corrida, nadie puede decir cuál índice produjo una cita.

**Las 3072 dimensiones por defecto.** Mejor calidad nominal, y con once documentos
el costo de almacenamiento es irrelevante. Se descarta porque deja el ANN fuera de
alcance de forma permanente: por encima de 2000, pgvector no indexa, y corregirlo
después cuesta re-embeber todo. La pérdida de calidad al truncar por MRL es
pequeña y **medible con la ablación de ADR-0011**; la del techo del índice es
estructural y no se mide, se sufre.

**Un modelo local (ONNX o `sentence-transformers`).** Sin clave, sin costo, sin
red, determinista por construcción y con CI hermético — era la opción por defecto
antes de saber que hay API de Gemini disponible. Se descarta porque agrega peso
sustancial al `pyproject` y por lo tanto a la imagen de GHCR, que es **el artefacto
de hand-off** ([ADR-0008](0008-el-artefacto-de-hand-off-es-el-digest.md)): ese peso
lo paga el compañero en cada pull, y la propiedad que el modelo local compraba
—reproducibilidad— ya está comprada por el índice persistido. Sigue siendo la
alternativa natural si el costo o la cuota se vuelven un problema, y por eso **el
proveedor entra por un puerto**: cambiarlo es un adaptador y un `index_version`
nuevo, no una reescritura.

**Un vector store dedicado** (Qdrant, Chroma, Milvus).
[ADR-0001](0001-postgres-con-pgvector-como-unica-base.md) ya decidió Postgres +
pgvector como única base, y once documentos no son el caso que justifica
revisarlo. Agregaría un servicio al `compose.yml` y al despliegue del compañero a
cambio de capacidades que este corpus no ejercita.

**Versionar el índice en el repositorio**, como `data/policies/`. Sería
reproducible por git, sin base, y el gate offline lo leería directo. Hay
precedente: `ground_truth.csv` es dato derivado y está commiteado con una guarda
`git diff --exit-code`. Se descarta porque el precedente no aplica: el ground
truth es legible, revisable en un diff y determinista desde un generador
sembrado. Un vector de 1536 floats no es ninguna de las tres cosas —un diff de
embeddings no se revisa, se acepta—.

**Podar las generaciones viejas al reindexar.** Deja una sola verdad en la tabla y
vuelve inofensivo olvidarse del filtro por `index_version`. Se descarta por dos
motivos: con once documentos el ahorro es nulo, y borrar la generación anterior
impide comparar índices antes de promover uno — que es el uso que la ablación de
ADR-0011 necesita. La seguridad que la poda compraba se compra más barato con el
filtro en el repositorio y su test (§6). **Se reabre** el día que el corpus haga
que el almacenamiento importe.

## Consecuencias

**Se gana la reproducibilidad de la única métrica del RAG.** Sobre vectores
persistidos, la ablación de ADR-0011 devuelve el mismo número dos veces. Sin esta
decisión, aquella sería inmedible y el ADR quedaría sin evidencia.

**Se gana una auditoría de tres ejes** que hoy no existe en ningún sistema del
proyecto: la decisión dice qué texto citó, qué traducción evaluó y con qué índice
recuperó.

**Se gana poder comparar dos índices sin destruir el anterior**, porque no hay
poda. El precio es que la corrección de la búsqueda pasa a depender de un `WHERE`
(§6): se paga con una función de búsqueda única en el repositorio y un test que la
vigila.

**Se paga la aparición de dato derivado que puede quedar viejo.** Un documento
publicado y no indexado es citable por identidad —si tiene vinculación— e
invisible por similitud. Es un estado nuevo, legítimo y silencioso, así que
necesita medición: **tercera métrica operativa del entregable 6, junto a
*políticas pendientes* y *vinculaciones obsoletas*: chunks pendientes de
indexar.**

**Se paga una dependencia externa en el camino crítico del grafo.** La query se
embebe en línea, una llamada por caso, con caché. Es la primera llamada de red
dentro de un superstep que no la tenía, y el nodo ya lleva `@degrades` por ADR-0011:
si el proveedor no responde, se pierde el descubrimiento y sobrevive la
autorización.

**Se paga que la indexación tiene que ser idempotente de verdad**, no "casi": corre
en cada despliegue como parte del seed, y una segunda corrida que duplique chunks
envenena el ranking sin que nada falle.

**No toca ADR-0001** —sigue siendo una sola base— ni **ADR-0011**, al que le da la
infraestructura que su pierna de descubrimiento necesita. **Refuerza ADR-0005**:
la reproducibilidad del harness se protege igual cuando la evidencia la produce un
tercero, y el mecanismo es congelarla, no confiar en ella.
