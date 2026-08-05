# Repaso — Etapa "RAG de políticas internas"
**Sistema Multi-Agente de Detección de Fraude · handoff de continuidad**

> Documento de cierre de etapa. Destila lo decidido y construido en
> `feature/policy-rag`, para retomar en el chat siguiente con el contexto ya
> condensado.
>
> Predecesor: `05-agentes-deterministicos.md`.
> Decisiones de fondo: `adr/0011-*`, `adr/0012-*`, `adr/0013-*`.

---

## 1. Qué se cerró en esta etapa

El **RAG de políticas de punta a punta**, y con él el bloqueo que arrastraban los
entregables 7 y 8: hasta ayer ningún caso podía decidirse solo.

| Pieza | Archivo | Verificado |
|---|---|---|
| Puerto de origen del catálogo | `domain/catalog.py` | 7 000/7 000 desde archivo |
| Catálogo en Postgres (4 tablas) | `db/models/{fraud_policy,binding_set,policy_binding,policy_chunk}.py` | 7 000/7 000 desde base |
| Chunker con `chunk_id` estable | `retrieval/chunking.py` | tests |
| Puerto de embeddings + Gemini | `retrieval/embeddings.py` | índice real |
| Indexación idempotente | `retrieval/indexing.py` | 2ª corrida: 0 nuevos |
| Búsqueda por generación | `db/repositories/policy_chunks.py` | `smoke_retrieval.py` |
| Query desde códigos, con caché | `retrieval/query.py` | 76 llamadas / 7 000 tx |
| Nodo RAG con dos bloques | `graph/nodes.py` | `smoke_decision.py` |
| Árbitro determinístico | `graph/nodes.py` | 3 escenarios en `DECIDED` |
| Explicabilidad (auditoría + cliente) | `explain/` | 17 tests de divulgación |
| Ablación de el bloque semántica | `scripts/check_retrieval.py` | curva k=1..10 |

**Cadena de migraciones**: `8990ef73796f` → catálogo (4 tablas) → sello del índice
→ sello del prompt.

---

## 2. El giro: una cita no es un resultado de búsqueda

La etapa empezó suponiendo lo que suponen casi todos los RAG: que
`citations_internal` sale de la búsqueda vectorial. Esa suposición produce un
fallo que **ninguna guarda del sistema detectaba**.

El motor dispara FP-03. El índice devuelve FP-05 y FP-02. El caso se decide
`BLOCK` —correctamente, porque la decisión viene del motor— y **cita normas que no
aplicó**. No hay excepción, `citations_internal` no está vacío, los dos artefactos
están íntegros. Lo que falló fue el emparejamiento, y el auditor recibe una
explicación coherente y falsa.

De ahí [ADR-0011](../adr/0011-citacion-por-identidad-descubrimiento-por-similitud.md)
y las **dos bloques**:

| bloque | Cómo | Aporta | Garantía |
|---|---|---|---|
| **Autorización** | lookup por `policy_id` contra el catálogo | toda política que disparó | **total** |
| **Descubrimiento** | búsqueda vectorial desde los códigos de señal | políticas relacionadas que no dispararon | ninguna |

Lo que se persiste es su unión. La primera respalda el veredicto; la segunda da
contexto al Arbiter y es la **única vía** por la que una política no evaluable
—`PENDING`, `EXCLUDED`— llega a un caso.

Medido: con el índice como única fuente, el 0.2% de los veredictos habría citado
mal (§5).

---

## 3. Las decisiones jugosas y su porqué

### 3.1 La autorización no consulta el índice

Se resuelve contra el catálogo y el constructor de `chunk_id`. Tres consecuencias,
y las tres son el punto:

1. **Recall 1.0 por construcción** — no hay recuperación aproximada de por medio.
2. **Sobrevive a que el índice no exista** — un documento publicado y no indexado
   sigue siendo citable. Si esta bloque consultara `policy_chunks`, ese estado
   dejaría de ser legítimo y pasaría a escalar el caso.
3. **Sobrevive a que el proveedor se caiga** — no hay red en este camino.

### 3.2 `@degrades` solo no alcanza

La decisión más importante del nodo. Si el proveedor de embeddings falla y la
excepción llega al decorador, el nodo devuelve **cero** citas: se pierde también
la autorización y **todo caso escala** — lo contrario de lo que ADR-0011 promete.

el bloque de descubrimiento lleva su **propio `try`** y registra el `AgentError` a
mano mientras la autorización sigue. El decorador queda como red para lo
imprevisto.

Verificado empíricamente: mismo caso, `BLOCK` con el proveedor sano y `BLOCK` con
el proveedor caído; confianza 0.4 → 0.25 y `degraded_agents = [internal_policy_rag]`.

### 3.3 El invariante se redactó como contención, no como "lista no vacía"

La formulación anterior fallaba por los dos lados.

**Débil**: una lista con las citas equivocadas la satisface (§2).

**Insatisfacible para `APPROVE`**: el catálogo rechaza al cargar cualquier
vinculación con `action: APPROVE` —*"`action` no puede ser APPROVE"*—, así que
ninguna cita puede respaldar una aprobación. Y el **90.7%** del tráfico no dispara
ninguna política. La redacción vieja mandaba a la cola humana a casi todo el
volumen.

> Cuando `decision != ESCALATE_TO_HUMAN`: `citations_internal` contiene una cita
> por cada `policy_id` de `matched_policies`, y `base_confidence` no es `null`.

**La obligación nace de la evidencia, no del veredicto.** `APPROVE` no necesita
exención: la condición se cumple vacíamente cuando no disparó nada.

Queda **fuera deliberadamente** la cláusula recíproca —*aprobar exige que no haya
disparado nada*—: convertiría en error el override pro-cliente que un Arbiter con
LLM podría querer hacer con justificación. Se decide en la rama del Arbiter.

### 3.4 El índice es dato derivado, versionado y sellado

[ADR-0012](../adr/0012-el-indice-vectorial-es-dato-derivado-y-versionado.md). Un
embedding llega por HTTP desde un modelo que el proveedor puede actualizar sin
aviso: si el harness llamara a la API en cada corrida, la evidencia del RAG
tendría la forma que ADR-0005 declaró **no evaluable**.

El corolario de no podar generaciones viejas:

> `WHERE index_version = <vigente>` deja de ser un filtro y pasa a ser un
> **invariante de corrección**.

Por eso vive en una única función de búsqueda del repositorio, con default y sin
admitir `None`: se puede elegir otra generación —comparar un índice candidato—,
no se puede consultar todas.

### 3.5 Cuatro sellos, y tres significan algo cuando son `null`

| Eje | Sello | `null` significa |
|---|---|---|
| Qué texto se citó | `InternalCitation.version` | — |
| Qué traducción se evaluó | `policy_catalog_version` | — |
| Con qué índice se recuperó | `retrieval_index_version` | **no hubo recuperación** |
| Con qué prompt se redactó | `explanation_prompt_version` | **ningún modelo participó** |

Los dos últimos son condicionales a propósito. Sellar la versión igual afirmaría
que un índice o un modelo participó en una decisión donde no participó.

### 3.6 El proveedor no es variable de entorno; la clave sí

Un modelo configurable por `env` podría cambiarse sin que suba la versión sellada,
y entonces los cuatro sellos mentirían a la vez. Modelo, dimensión, plantillas y
estrategia de chunking viven en **código**, en el mismo módulo que compone la
cadena de versión — de modo que cambiar uno la mueve sola.

Asimetría entre proveedores que salió de la documentación: desde la generación 4.6,
los IDs de modelo de Anthropic son **fijos** —el ID canónico apunta a un snapshot
que no se actualiza—. El riesgo central de ADR-0012 no aplica del lado de la
generación: ahí el segmento de modelo es una garantía del proveedor.

### 3.7 La explicación al cliente omite lo que la de auditoría dice

**Explicarle la regla al titular es entregársela a quien quizás sea el
defraudador.** *"Cuatro operaciones del mismo dispositivo en cinco minutos"* revela
el umbral y la ventana: la próxima ráfaga son tres en seis minutos.

`explanation_customer` nunca contiene `policy_id`, códigos de señal, umbrales,
ventanas ni conteos. El LLM recibe **temas seguros** ya traducidos: nunca ve un
código. Un modelo con permiso de nombrar políticas reintroduciría en el texto del
cliente el fallo que ADR-0011 cerró en las citas.

`MERCHANT_BLACKLISTED` se trata aparte: decirle por escrito a un cliente que *ese
comercio tiene historial de fraude* es una afirmación sobre un tercero hecha sin
proceso. Se dice que la operación necesita verificación, no por qué.

> El mapa `SAFE_THEMES` es un diccionario **a mano**, al revés de la regla que
> `retrieval/query.py` sigue —derivar el vocabulario del catálogo—. Es deliberado:
> la frase del predicado *describe la regla*, y describir la regla es exactamente
> lo prohibido. Dos artefactos con propósitos opuestos, no una duplicación.

### 3.8 Plantilla para lo que se audita, LLM para lo que se lee

`explanation_audit` sale de una plantilla determinística. Es el registro de la
decisión: dos corridas de la misma transacción tienen que producir el mismo texto,
o el diff del entregable 7 es ruido. Nunca depende del proveedor.

Es la tercera vez que el proyecto hace esta distinción: `Decimal` para el dinero y
`float` para el score; tabla para lo que se **mide** y JSONB para lo que se
**archiva**; plantilla para lo que se **audita** y LLM para lo que se **lee**.

### 3.9 El árbitro determinístico se adelantó

El plan lo ponía al final y marcado como *"lo primero que se corta"*. Se adelantó
porque sin él ningún caso llega a `DECIDED`, las tres guardas de W2 no se
ejercitan y la ablación no tiene de dónde sacar *"cuántos casos salen de
`ESCALATE_TO_HUMAN`"*. Es además el brazo de control que ADR-0006 prometió.

Degrada a `ESCALATE_TO_HUMAN` **antes** de que las guardas puedan dispararse: que
una guarda levante significa `FAILED`, y la ausencia de respaldo no es un error del
sistema sino la razón por la que existe la cola humana.

---

## 4. Convenciones nuevas fijadas

- **El puerto se corta antes de la derivación.** `CatalogSource` devuelve registros
  crudos con la forma de entrega; `build_catalog` valida y deriva, y es **una
  sola** implementación. Si el puerto devolviera objetos ya construidos, el test
  que afirma que dos fuentes coinciden compararía dos copias del mismo bug.
- **Puertos síncronos para lo que se lee una vez por proceso**, async para lo que
  corre por caso. `GraphContext.catalog` lo toma de un `default_factory`, que no
  puede esperar una corrutina.
- **`asyncio.to_thread` para todo cliente de proveedor.** Son síncronos: llamarlos
  directo dentro de un nodo bloquea el event loop y, con él, las ramas hermanas
  del superstep.
- **Un doble de prueba lleva su propia versión.** `--fake` escribe bajo
  `fake:1536:doc:1`: lo que impide que un vector de prueba se cuele en el índice
  real no es la disciplina, es el mismo filtro por generación que ya existe.
- **Saltear no es optimización.** Re-embeber un texto sin cambios abriría la puerta
  a que el proveedor devuelva otro vector bajo la misma versión — el riesgo que
  ADR-0012 existe para cerrar.
- **El texto que se persiste es prosa plana.** Sin markdown: el formato lo decide
  quien lo muestra, y el contrato no declara ninguno.
- **Upsert también para lo append-only.** *Append-only* significa que una versión
  nueva no pisa a la vieja, no que una fila no pueda corregirse para volver a
  coincidir con el archivo que la originó.

### Footguns documentados

| Trampa | Detalle |
|---|---|
| `import pgvector` | no importa el submódulo; hace falta `import pgvector.sqlalchemy` |
| Lote de embeddings | con varias entradas sueltas, `gemini-embedding-2` devuelve **un** vector agregado, sin error |
| `SET active = (version = :v)` | viola el índice parcial único a mitad de sentencia; apagar y encender en dos |
| Índice sobre la columna líder de la PK | redundante: la PK ya crea ese B-tree |
| `chunk_id` entre generaciones | es **idéntico** por diseño; no sirve para probar el filtro |

---

## 5. Verificación de la etapa

| Gate | Resultado |
|---|---|
| `pytest` | 161 verdes, sin red y sin base |
| `check_policies.py` | 7 000/7 000 desde archivo |
| `check_policies.py --source=db` | 7 000/7 000 desde Postgres |
| `smoke_catalog_sources.py` | 11 políticas idénticas en ambas fuentes |
| `index_policies.py --fake` (2ª vez) | 0 indexados, 11 filas |
| `smoke_retrieval.py` | 11/22 por generación; distancia 0.967 contra la falsa |
| `smoke_decision.py` | 3 escenarios en `DECIDED` |

### La ablación

| k | recall | azar | sobre azar |
|---|---|---|---|
| 1 | 0.787 | 0.091 | **+0.696** |
| 3 | 0.960 | 0.273 | +0.687 |
| 5 (operativo) | 0.998 | 0.455 | +0.544 |
| 10 | 1.000 | 0.909 | +0.091 |

MRR 0.879. Único hueco: **FP-02, 77 de 79** a k=5.

**El número que se cita es el de k=1.** Con once documentos, k=5 es el 45% del
corpus y k=10 el 91%: a esos k la métrica mide el tamaño del corpus, no el
recuperador. La fila de k=10 está en la tabla para hacerlo visible.

### Lo que la etapa desbloqueó

| Veredicto | Casos | % |
|---|---|---|
| `APPROVE` | 6 347 | 90.7% |
| `ESCALATE_TO_HUMAN` | 286 | 4.1% |
| `BLOCK` | 252 | 3.6% |
| `CHALLENGE` | 115 | 1.6% |

**De 100% escalando por falta de respaldo interno a 4.1%**, y ese 4.1% sólo porque
FP-02 y FP-07 lo prescriben.

---

## 6. Hallazgos y deuda

### 6.1 La ablación está sesgada a favor del descubrimiento

La query se arma con las `description` de los predicados y, con un chunk por
documento, el índice contiene casi ese mismo texto: buscar la política que produjo
la señal es casi buscar el texto por sí mismo. **El recall es alto por
construcción, no por mérito**, y el informe tiene que decirlo.

Es la contracara del límite ya declarado —el corpus de once líneas sobredimensiona
el bloque de identidad—: también sobredimensiona la otra.

### 6.2 Una prueba que no puede fallar es peor que no tenerla

La primera versión de `smoke_retrieval.py` comparaba conjuntos de `chunk_id` entre
generaciones para verificar el filtro. No prueba nada: una fila se identifica por
`(index_version, chunk_id)` y el `chunk_id` es idéntico entre generaciones **por
diseño**. Una de las dos comprobaciones dio falso positivo —se notó— y la otra
habría dado verde para siempre. Lo que discrimina es el **conteo** y la
**distancia**.

### 6.3 La costura entre el contexto y los nodos no tiene red

`pytest` dio 161 verdes con un `GraphContext` al que le faltaban tres campos: la
suite corre sin base y sin red, así que ningún test arma el contexto completo. El
error apareció recién en el smoke. El día que haya Postgres en CI, un test que
arme el contexto con dobles y corra el grafo de punta a punta cubre el hueco.

### 6.4 `check_retrieval.py` no puede ser gate de CI todavía

Necesita el índice en Postgres y los embeddings de las queries. El caché vive en el
proceso, así que un runner siempre es la primera corrida. Las salidas son una tabla
`query_embeddings` con un artefacto que CI restaure, o declarar que corre contra
una base poblada y no en el job de PR. **Decidido: lo segundo, por ahora.**

### 6.5 Menor

- `logger.exception` imprime el stack completo: una caída real del proveedor
  produciría un traceback por caso —7 000 en una corrida—. Candidato a bajar a
  `warning` cuando haya logging estructurado.
- **`SAFE_THEMES` necesita revisión con criterio legal**, no técnico. En particular
  `MERCHANT_BLACKLISTED`.
- La autorización cita el **ordinal 0**. El día que el chunker parta por párrafo
  hay que decidir si cita el fragmento que corresponde o todos.

---

## 7. Mapa de archivos al cierre

```
src/multiagent_fraud_detection/
├── domain/catalog.py                 # + RawCatalog, CatalogSource, FileCatalogSource
├── retrieval/
│   ├── chunking.py                   # Chunk, chunk_id_for, estrategias
│   ├── embeddings.py                 # puerto, Gemini, INDEX_VERSION, plantillas
│   ├── indexing.py                   # index_catalog (idempotente)
│   ├── query.py                      # vocabulario, build_query, QueryCache
│   └── citations.py                  # autorización + unión + invariante
├── explain/
│   ├── audit.py                      # plantilla determinística
│   ├── customer.py                   # SAFE_THEMES, prompt, PROMPT_VERSION
│   └── narrator.py                   # puerto + Anthropic + Fake
├── db/
│   ├── models/{fraud_policy,binding_set,policy_binding,policy_chunk}.py
│   └── repositories/{policy_catalog,policy_chunks}.py
└── graph/
    ├── context.py                    # + embedder, narrator, query_cache, vocabulary
    ├── nodes.py                      # RAG, árbitro determinístico, explicabilidad
    └── state.py                      # + los dos sellos

scripts/
├── index_policies.py                 # CLI de indexación
├── check_retrieval.py                # ablación
├── smoke_catalog_sources.py          # archivo vs base
├── smoke_retrieval.py                # invariante de generación
└── smoke_decision.py                 # el primer DECIDED
```

---

## 8. Qué sigue

**Inmediato**: publicar el contrato **v0.7**. Hay ocho enmiendas acumuladas y el
vigente es v0.6; ADR-0008 a 0010 esperan validación del compañero para §1.

**La rama del Arbiter con LLM.** El determinístico es el brazo de control; el
agéntico se mide contra él (entregable 7). Ahí se decide la cláusula recíproca del
invariante (§3.3) y el ajuste de confianza con justificación auditable.

**Los agentes que faltan del reto**: Threat Intel —que trae consigo
`web_search_allowlist`, la última tabla del contrato sin modelar— y los Debate
Agents.

**Entregable 7 completo**: el harness ya tiene brazo de control, métricas
determinísticas y un carril LLM-as-judge separado por ADR-0013.

---

## 9. Documentación asociada

- `adr/0011-citacion-por-identidad-descubrimiento-por-similitud.md`
- `adr/0012-el-indice-vectorial-es-dato-derivado-y-versionado.md`
- `adr/0013-que-se-mide-con-metricas-duras-y-que-con-llm-as-judge.md`
- `enmiendas_pendientes.md` — ocho enmiendas hacia v0.7
- `05-agentes-deterministicos.md` — etapa anterior
