# ADR-0014: la inteligencia externa se recoge en tiempo de build y se consulta congelada

- **Estado**: aceptado
- **Fecha**: 2026-08-05

## Contexto

El reto exige un External Threat Intel Agent con **búsqueda web gobernada**, y el
§4 del contrato especifica desde v0.2 una tabla `web_search_allowlist` que nunca
se modeló. Es la última tabla pendiente.

La práctica real del rol —monitoreo de feeds de IoC, campañas de phishing,
indicadores de compromiso— es mayoritariamente **prueba de pertenencia contra un
feed**, no búsqueda en texto libre. Un feed de amenazas ya viene fechado y con
corte: es un artefacto versionado por naturaleza.

Contra eso choca el principio que gobierna los gates del proyecto:

> Los gates determinísticos tienen que dar el mismo número dos veces.

Una búsqueda web dentro del grafo lo rompe por construcción. Es el mismo problema
que [ADR-0005](0005-exclusion-de-fp-10-por-evidencia-no-reproducible.md) detectó,
y el mismo que [ADR-0012](0012-el-indice-vectorial-es-dato-derivado-y-versionado.md)
ya resolvió para los embeddings: **recolectar una vez, persistir, sellar la
versión**.

Hay además un problema de costo que la decisión resuelve de paso: la búsqueda web
de la API de Anthropic se cobra por búsqueda ejecutada. Una por transacción son
7 000 búsquedas por corrida del harness, no reproducibles y pagas.

## Decisión

**El grafo no sale a la red.** La inteligencia externa se recoge en un paso de
build —`scripts/fetch_threat_intel.py`— que ejecuta la búsqueda gobernada,
aplica el allowlist **en el camino de escritura**, y persiste el resultado en la
tabla `threat_indicators` sellado con un `snapshot_version`.

En tiempo de ejecución el nodo `external_threat_intel` hace **lookup**, nunca
búsqueda. La versión del snapshot consultado se sella en
`decisions.threat_intel_version` — el quinto eje de auditoría, con la misma
semántica de nulo que los otros dos: `null` significa *no se consultó snapshot*,
no dato faltante.

Simetría exacta con el RAG de políticas:

| | Políticas | Amenazas |
|---|---|---|
| Build | `index_policies.py` | `fetch_threat_intel.py` |
| Artefacto | `policy_chunks` + `INDEX_VERSION` | `threat_indicators` + `SNAPSHOT_VERSION` |
| Runtime | `search_similar` | lookup exacto + ventana *as-of* |
| Sello | `retrieval_index_version` | `threat_intel_version` |

**El allowlist gobierna la escritura, no la lectura.** Una fuente fuera de la
lista no llega a la base; lo rechazado se registra en el informe del script. Por
eso `discarded_sources` sale del estado del grafo: en runtime no hay nada que
descartar, porque nada indebido entró.

El proveedor de búsqueda entra por un tercer puerto, `Searcher`, con el mismo
patrón que `Embedder` y `Narrator`: adaptador de Anthropic, cliente perezoso,
sólo la clave por `env` —el modelo y las plantillas viven en código, porque
configurables por entorno podrían cambiar sin que suba el sello—. El puerto lo
consume el script, no el grafo.

## Alternativas descartadas

**Búsqueda en vivo dentro del nodo, con caché por proceso.** Es lo que sugiere la
lectura literal del reto. Se descarta por tres motivos que se refuerzan: el gate
deja de ser reproducible; la latencia de red no acotada entra al superstep 0 y
bloquea a Context y Behavioral en el fan-in; y el costo escala con el volumen de
transacciones en vez de con el tamaño del corpus. El caché mitiga lo tercero y no
toca lo primero, que es lo que importa.

**Snapshot sembrado a mano con alertas que escribimos nosotros.** Es la
alternativa que ADR-0005 rechazó, y sigue rechazada: mediría la capacidad del
sistema de consultar una tabla que nosotros llenamos. La diferencia con lo que
aquí se decide es el **origen del dato**: el snapshot trae contenido real de la
web, con URL y `retrieved_at` verificables, y después lo congela. Congelar un
dato real no es fabricarlo.

**Dos tablas separadas —indicadores por un lado, citas web por el otro—.** Fue el
diseño de la primera pasada. Se descarta porque las dos filas dicen lo mismo con
otra forma: un indicador *es* una alerta con una fuente. Separarlas obligaba a
mantener sincronizadas dos escrituras del mismo hecho, que es la clase de
desincronización que §3 del contrato ya cataloga tres veces.

**Guardar el allowlist como variable de entorno.** Descartado desde v0.2 del
contrato y sin cambios: es dato de gobernanza —mutable, administrado por un
humano, con audit trail—, no configuración de despliegue.

## Consecuencias

**Se gana** un nodo que no puede fallar por red: su única dependencia es Postgres,
y su degradación es la de cualquier lectura. `@degrades` deja de ser la red que
atrapa lo probable y vuelve a ser la que atrapa lo imprevisto.

**Se gana** un costo acotado y conocido: el número de búsquedas depende de las
claves distintas del catálogo de emisores, no del volumen transaccional.

**Se paga la frescura.** El sistema no consulta la web en el momento de decidir:
consulta una foto. Un indicador publicado después del último `fetch` no existe
para el sistema hasta que alguien vuelva a correrlo. Es la misma deuda que el
índice vectorial ya tiene, y tiene la misma métrica de operación —antigüedad del
snapshot vigente— y la misma salida a futuro: un feed en streaming, que es
material del entregable 10.

**Se paga una fidelidad literal al enunciado.** El paso 5 del flujo de ejemplo
del reto describe una búsqueda ejecutada durante el análisis del caso. Acá la
búsqueda ocurrió antes; lo que el caso ejecuta es la consulta. El informe tiene
que decirlo con esas palabras, porque la diferencia es real.

**`threat_indicators` es la tabla trece** y con ella el contrato queda sin
ninguna tabla pendiente por primera vez desde v0.2.
