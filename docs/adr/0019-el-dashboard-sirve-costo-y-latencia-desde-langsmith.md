# ADR-0019: el dashboard sirve costo y latencia desde la API de lectura de LangSmith

- **Estado**: aceptado
- **Fecha**: 2026-09-03

## Contexto

ADR-0013 ya decidió LangSmith como la capa de observabilidad del proyecto;
el wiring (`wrap_anthropic` sobre los tres clientes) se conectó y se
verificó de punta a punta contra el proyecto real — trazas completas,
tokens y costo por corrida, visibles en la consola de LangSmith.

Ese dato hoy vive únicamente ahí. El dashboard tiene dos tarjetas
pendientes (`Dashboard.tsx`) esperando exactamente esto — **"Latencia y
costo por nodo"** declara explícitamente que depende de conectar LangSmith
al backend. Ya está conectado; falta el camino que traiga esos números al
dashboard y se actualicen solos con cada ejecución real, de cualquier
visitante, sin que nadie tenga que abrir LangSmith aparte.

Antes de decidir la forma, se verificó en vivo contra el proyecto real qué
tan bien se presta la API de lectura de LangSmith a esto:
`client.get_run_stats(project_names=[...], is_root=True)` da en una sola
llamada todo lo agregado (`total_cost`, `cost_p50`, `latency_p50`,
`total_tokens`, `error_rate`); `client.list_runs(is_root=False)` agrupado
por `run.name` en Python da el desglose por nodo real del grafo, ya con el
costo de sus descendientes LLM acumulado (no hace falta sumarlo aparte).
De paso se encontró y se corrigió un defecto real: `decision_arbiter`
mostraba $0 de costo en LangSmith pese a generar tokens reales —
`judge.py` envuelve `messages.parse` con `traceable` manualmente (
`wrap_anthropic` no llega ahí) y no declaraba `usage_metadata` ni el
proveedor/modelo que LangSmith necesita para tarifar. Se arregló pasando
`process_outputs` (el mismo serializador que ya usa el wrapper oficial) y
`metadata={"ls_provider": ..., "ls_model_name": ...}` — verificado en vivo
que ya calcula costo real.

## Decisión

**Nuevo endpoint `GET /api/v1/metrics/llm`** en el backend: llama a
`get_run_stats` para el resumen y a `list_runs` agregado por nodo para el
desglose, y le sirve ambos al dashboard.

- **Nunca un 500 por esto.** Si `LANGSMITH_TRACING`/`LANGSMITH_API_KEY` no
  están configurados, el endpoint no llama a nada externo — mismo criterio
  que ya usa `propagar_langsmith()` en `settings.py` — y responde un estado
  explícito de "sin datos". Si LangSmith está configurado pero no responde,
  mismo criterio: se degrada, no rompe la carga del resto del dashboard.
- **Caché de proceso, TTL corto (30–60s).** Evita golpear la API de
  LangSmith en cada poll del frontend si hay varias pestañas abiertas — el
  dato no necesita ser instantáneo, necesita no mentir.
- El frontend consume por **polling** (`useQuery`/`refetchInterval`),
  mismo patrón que ya usan `Queue.tsx`/`CaseDetail.tsx` — no WebSocket,
  consistente con el resto del proyecto.

## Alternativas descartadas

**Consultar LangSmith directo desde el navegador.** Expondría
`LANGSMITH_API_KEY` al cliente — inaceptable, mismo criterio que cualquier
otra clave de proveedor en este proyecto: nunca viaja al frontend.

**Persistir costo/latencia en Postgres en cada corrida** (columnas nuevas
en `decisions`, por ejemplo). Duplicaría una fuente de verdad que LangSmith
ya mantiene mejor —percentiles, tasa de error, todo gratis en el mismo
llamado— y agregaría una escritura más al camino caliente del grafo por un
dato que sólo alimenta una vista secundaria del dashboard. No vale la
complejidad.

**Sin caché, pegarle a LangSmith en cada poll.** El resto del dashboard ya
sondea cada pocos segundos; multiplicar eso por cada pestaña abierta de un
visitante mirando el dashboard serían llamadas innecesarias a un servicio
de terceros con su propio límite de uso, por un número que no cambia tan
rápido.

**`client.runs.query()`**, la API que reemplaza a `list_runs` (deprecado).
Descartada por ahora: en la versión instalada del SDK (`langsmith==0.10.18`)
tiene una firma distinta e incompatible
(`query_v2() got an unexpected keyword argument 'project_name'`), no es un
reemplazo directo todavía. `list_runs` se retira recién después de
2027-01-31 — hay margen de sobra; se anota como deuda de actualización, no
bloquea esta decisión.

**Guardar el `trace_id` de LangSmith en `decisions`** para mostrar
costo/latencia de un caso puntual (por fila, dentro de "Decisión del
LLM"). Fuera de alcance: exigiría una columna nueva y una migración para
algo que no se pidió —esta etapa es la vista agregada del dashboard, no el
detalle por caso—. Queda declarado como posible extensión futura, no como
parte de esta decisión.

## Consecuencias

**Se gana** una demostración real de instrumentación y costo para quien
revise el proyecto —no sólo se construyeron agentes, se miden—, sin
exponer secretos ni tocar la ruta caliente del grafo.

**Se paga**: ésta es la primera vista del dashboard cuyo dato depende de
verdad de un servicio externo. Si LangSmith está mal configurado o caído,
esa vista puntual queda en "sin datos" —declarado, nunca un error
genérico que tumbe el resto del dashboard—.

**El desglose por nodo depende de una función deprecada** (`list_runs`).
Con más de un año de margen antes del retiro, y con la ruta de reemplazo
ya identificada (`client.runs.query()`, pendiente de que su firma madure
en una versión más nueva del SDK), queda como deuda anotada, no oculta.
