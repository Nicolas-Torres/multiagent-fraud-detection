# Repaso — Etapa "Grafo y persistencia"
**Sistema Multi-Agente de Detección de Fraude · handoff de continuidad**

> Documento de cierre de etapa, escrito retroactivamente: cubre
> `feature/graph-state` y `feature/decision-persistence`, que se cerraron sin
> acta y cuyos hallazgos quedaron estacionados en `enmiendas_pendientes.md` §3.
>
> Predecesor: [`02-domain-models.md`](02-domain-models.md).
> Sucesor: [`04-dataset-y-seed.md`](04-dataset-y-seed.md).
> Contrato al cierre: v0.4.

---

## 1. Qué se cerró en estas dos etapas

El esqueleto completo del sistema de agentes: el estado, los diez nodos, la
topología y el único punto donde el grafo toca la base.

| Entregable | Estado |
|---|---|
| `GraphState` — cuatro zonas, tres reducers | ✅ |
| `GraphContext` — dependencias de runtime | ✅ |
| Diez nodos como stubs con firma definitiva | ✅ |
| Decorador `@degrades` en los nodos de evidencia | ✅ |
| Topología con dos olas de paralelismo | ✅ |
| Cuatro columnas de scoring en `decisions` | ✅ |
| Tabla `agent_errors` | ✅ |
| Nodo persistidor con reemplazo del agregado | ✅ |
| Diagrama de topología autogenerado | ✅ |

**Migraciones**: `307787653e5e` (scoring) y `694142a4c8b6` (`agent_errors`).

Los nodos son **stubs con contrato definitivo**: cada uno escribe una constante
en su clave y registra su paso. Se reemplazan de a uno sin tocar el cableado.

---

## 2. Las decisiones jugosas y su porqué

### 2.1 `TypedDict`, no Pydantic, para el estado

El estado se llena **progresivamente**: en el superstep 1 casi todas las claves
están ausentes. Con Pydantic, eso obliga a declarar todo `Optional` con default
`None` — y ahí la validación deja de validar nada, porque `None` siempre pasa.

`TypedDict` con `total=False` expresa exactamente esa semántica: **la ausencia de
una clave significa "todavía no"**, y se lee con `.get()`.

Corolario incómodo pero honesto: en un `TypedDict` nada valida en runtime. Por eso
`risk_score` es `float` y no el alias `Confidence` — el rango se hace cumplir
donde el valor se produce, no en la anotación.

### 2.2 Reducers solo donde hay varios escritores

Tres claves los necesitan: `signals`, `agent_route` y `agent_errors`. Son las que
reciben aportes de nodos que corren en el mismo superstep.

Las demás usan semántica de última escritura porque tienen **un escritor cada
una**. Los dos nodos de debate corren en paralelo y no necesitan reducer:
escriben claves distintas (`pro_fraud_argument` y `pro_customer_argument`).

Trampa asociada: con reducer, **un nodo devuelve solo su aporte**. Devolver la
lista acumulada duplica en silencio.

### 2.3 `@degrades` es obligatorio, no defensivo

Verificado empíricamente: **si un nodo de un superstep paralelo lanza, se pierden
también los resultados de sus hermanos del mismo superstep**. La pérdida es
atómica.

O sea que sin el decorador, un fallo del agente de amenazas externas se lleva por
delante el trabajo del agente de contexto y del de comportamiento, que ya habían
terminado bien. La degradación parcial no existiría: sería todo o nada.

El decorador captura y convierte la falla en evidencia (`agent_errors`), no en
excepción. `FAILED` queda reservado para una excepción no capturada, y la escribe
el background task, no el grafo.

Deja una **marca estructural** (`wrapper.degrades_as`) para que un test pueda
afirmar que ningún nodo de evidencia quedó sin decorar al agregarse.

### 2.4 El reintento va adentro del nodo

`@degrades` es incompatible con el `RetryPolicy` de LangGraph, que solo dispara
ante una excepción que **salga** del nodo. Como el decorador es justamente lo que
impide que salga, el reintento tiene que vivir en el cuerpo de la función.

No es una limitación que se pueda esquivar: son dos mecanismos que compiten por
el mismo punto de intercepción, y hay que elegir uno. Se eligió la degradación.

### 2.5 Cero aristas condicionales

`DECIDED` frente a `PENDING_HUMAN` es un **valor de `status`** que escribe el nodo
persistidor, no una bifurcación del grafo.

La tentación era modelarlo como arista condicional después del Arbiter. Se
descartó porque las dos ramas hacen exactamente lo mismo —persistir la decisión—
y solo difieren en un campo. Una bifurcación habría duplicado el nodo terminal
para expresar un `if` de una línea.

Consecuencia: la topología es un DAG plano, el diagrama se lee de un vistazo, y
agregar un estado nuevo no toca el cableado.

### 2.6 `PENDING_HUMAN` como estado terminal, no `interrupt()`

LangGraph ofrece `interrupt()` para HITL. Se descartó.

`Command(resume=)` no transportaba nada útil —la resolución del analista llega por
`POST /cases/{id}/resolution` y se escribe en su propia tabla— mientras que
mantener el hilo suspendido costaba un thread del checkpointer por cada caso
pendiente. Se pagaba infraestructura por un mecanismo que no se usaba.

Con `PENDING_HUMAN` terminal, el grafo termina, la cola HITL es una consulta
sobre `cases.status`, y el caso resuelto no reanuda nada: ya está decidido.

### 2.7 Sin checkpointer

Consecuencia de 2.6, y de que los nodos de evidencia capturan su propia falla.
Lo único que un checkpointer cubriría es la **muerte del proceso** a mitad del
grafo — y eso sale más barato con una consulta sobre casos estancados en
`ANALYZING` que con persistir cada superstep de cada caso.

Se revisa el día que un nodo se vuelva caro de recomputar (una llamada a LLM de
varios segundos que se pierda por un reinicio).

### 2.8 Reemplazo del agregado en la persistencia

El nodo persistidor hace `DELETE` + `INSERT` en una sola transacción, no `UPSERT`
fila por fila.

> El resultado de este nodo para este caso **es exactamente esto**, no
> "asegúrate de que estas filas existan".

Un reintento sustituye, no complementa. Sin eso, un reintento sumaría señales a
las del intento anterior y el caso quedaría con evidencia duplicada.

La clave de idempotencia es `case_id`, que ya es PK de `decisions`, y el
`ON DELETE CASCADE` barre `signals` y `agent_errors` sin nombrarlas.

Detalle no obvio: se usa `delete()` de Core y **no** un borrado por objeto. Con
`lazy="selectin"` el ORM cargaría todos los hijos para borrarlos uno por uno, en
vez de dejar que la cascada de la base haga su trabajo.

### 2.9 Los invariantes se verifican antes de escribir, no después

`_verificar_invariantes` corre al entrar al nodo persistidor y lanza si el estado
es incoherente:

- Un veredicto autónomo sin respaldo interno (`citations_internal` vacío).
- Un veredicto autónomo sin score determinístico.
- Una confianza que el Arbiter ajustó sin justificar.

`ESCALATE_TO_HUMAN` queda **exento** de los dos primeros, y la excepción es
deliberada: diferir a un humano no es un veredicto. Sin ella, un caso sin citas no
tendría ninguna salida posible — ni decidir ni escalar.

### 2.10 `GraphContext` no es estado

Las dependencias de runtime van por `context_schema`, no por el estado: no mutan
entre nodos, no se checkpointean y pueden contener objetos no serializables.

El caso que lo fuerza: **el nodo persistidor no puede usar la sesión del
request**. Ese request ya devolvió `202` y el grafo corre en segundo plano.
Necesita su propia sesión y su propio commit.

Se prefirió `context_schema` a un import global de la factory porque un import
global vuelve el grafo imposible de probar contra una base distinta.

### 2.11 `agent_route` no incluye al persistidor

El campo es el rastro de los **agentes**. El nodo persistidor es la costura con la
base, no un agente. Que corrió lo prueba la fila que dejó, no una cadena en una
lista.

Es la misma distinción que separa `status` de `decision`: qué etapa del pipeline
ocurrió frente a qué se decidió.

---

## 3. Convenciones nuevas fijadas

- **Nombres de nodo como constantes.** Los consumen el builder y `agent_route`; un
  typo entre ambos produce un grafo que **compila y no corre**.
- **Sin `from __future__ import annotations`** en `state.py`: LangGraph resuelve
  las anotaciones en runtime para descubrir los reducers, y las anotaciones
  diferidas se las esconden.
- **`input_schema=` al compilar**: fija que el grafo solo recibe `case_id` y
  `transaction`. Sin él, cualquier clave del estado sería un punto de entrada
  válido.
- **Sin `output_schema`**: nadie lee el retorno del grafo. El dashboard hace
  polling contra las tablas.
- **Tipos internos no cruzan a `schemas/`.** `WorkingSignal` lleva `emitted_by`
  para que Evidence Aggregation fusione redundantes y el harness atribuya falsos
  positivos; se descarta al persistir, porque el contrato define `Signal` sin
  procedencia expuesta al cliente.
- **Un nodo devuelve solo las claves que escribe.**

### Footguns documentados

| Trampa | Detalle |
|---|---|
| Pérdida atómica en superstep | Un nodo que lanza se lleva los resultados de sus hermanos del mismo superstep |
| `RetryPolicy` vs captura | Solo dispara ante excepción que **sale** del nodo; capturar adentro lo desactiva |
| Reducer y aporte | Devolver la lista acumulada en vez del aporte duplica en silencio |
| `lazy="selectin"` y borrado | El ORM carga los hijos para borrarlos uno por uno; usar `delete()` de Core |
| `None` ambiguo | `customer_snapshot=None` no comunica "cliente sin perfil"; eso lo dice la señal `NO_CUSTOMER_PROFILE` |
| Mermaid en README | Los `classDef` de LangGraph traen colores fijos que se rompen en modo oscuro |

---

## 4. Verificación de la etapa

Tres smoke tests, cada uno sobre una propiedad distinta:

| Script | Qué prueba |
|---|---|
| `smoke_graph.py` | supersteps, reducers, `input_schema` |
| `smoke_degradation.py` | un agente caído no aborta el grafo ni pierde a sus hermanos |
| `smoke_persistence.py` | un reintento no duplica señales |

El segundo es el que justifica `@degrades`: sin el decorador, el test falla
mostrando que se perdieron los resultados de los nodos que sí funcionaron.

**Diagrama de topología** (`docs/diagrams/graph_topology.png`), generado con
`draw_mermaid_png` y guarda de comparación por bytes. Se probó inyectar el
Mermaid directamente en el README y se abandonó: los `classDef` que emite
LangGraph traen colores fijos que se vuelven ilegibles en modo oscuro. La
exportación a PNG con fondo blanco es la vía estable.

---

## 5. Hallazgos de infraestructura del mismo período

Un tercer hilo corrió en paralelo —la puesta en marcha de la base compartida en
AWS— y dejó hallazgos que no pertenecen ni al grafo ni al dataset. Se registran
acá por cercanía temporal:

- **El directorio de datos cambió en Postgres 18.** Un volumen montado con la ruta
  de 17 arranca vacío.
- **El usuario master de RDS no es superusuario**: es `rds_superuser`. Algunas
  extensiones que instalan código C quedan fuera de su alcance.
- **`pg_available_extensions` lista lo que el motor puede instalar**, no lo
  instalado. Confundirlas hace creer que pgvector ya está activo.
- **Las variables exportadas contaminan `docker compose`.** Un `DATABASE_URL`
  exportado en la shell gana sobre el `.env` y el contenedor arranca apuntando a
  otro sitio.

Los cuatro están reflejados en el contrato v0.5 §1.4.

---

## 6. Mapa de archivos al cierre

```
src/multiagent_fraud_detection/
├── graph/
│   ├── state.py          # GraphInput/GraphState, 4 zonas, tipos internos
│   ├── context.py        # GraphContext: dependencias de runtime
│   ├── nodes.py          # @degrades + 10 nodos + persistidor
│   └── builder.py        # topología, dos olas, cero condicionales
├── db/models/
│   ├── decision.py       # + risk_score, base_confidence,
│   │                     #   confidence_rationale, scoring_version
│   └── agent_error.py    # tabla, no JSONB
scripts/
├── smoke_graph.py
├── smoke_degradation.py
├── smoke_persistence.py
└── export_graph_diagram.py
docs/diagrams/graph_topology.png
```

---

## 7. Deuda que esta etapa dejó abierta

- **Un test no es dueño de la base.** `smoke_read.py` limpiaba al entrar pero no
  al salir, y sus dos fixtures contaminaban la tabla. Lo detectó el smoke test del
  seed al contar filas. Arreglado en la etapa siguiente; la salida definitiva es
  aislamiento transaccional cuando llegue `pytest`.
- **Los diez nodos siguen siendo stubs.** El contrato de retorno es definitivo,
  pero ninguno implementa lógica.
- **`_verificar_invariantes` lanza y no degrada.** Es deliberado —un estado
  incoherente no debe llegar a la base— pero significa que un bug en el Arbiter se
  manifiesta como excepción del grafo, no como caso degradado.
- **Sin checkpointer, un proceso muerto deja el caso en `ANALYZING` para
  siempre.** Hace falta la consulta de casos estancados; no existe todavía.

---

## 8. Documentación asociada

- `contrato_de_interfaz.md` — §7.2 (`agent_errors`: tabla, no JSONB),
  §7.3 (los cuatro puntos de escritura).
- [`02-domain-models.md`](02-domain-models.md) — etapa anterior.
- [`04-dataset-y-seed.md`](04-dataset-y-seed.md) — etapa siguiente.
- `docs/diagrams/graph_topology.png` — topología autogenerada.
