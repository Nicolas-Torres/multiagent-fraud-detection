# Evaluación: ¿conviene migrar de LangSmith a Langfuse?

> Fecha: 2026-10-11. Análisis de escritorio: no tocó código ni producción.
> Precios leídos de las páginas oficiales ese día; lo que no se pudo confirmar
> en fuente oficial está marcado.

## Conclusión

**No migrar ahora.** La premisa "LangSmith es para desarrollo y Langfuse para
producción" no es correcta: los dos son plataformas de observabilidad para
producción, con trazas, costos, dashboards y evaluaciones en línea. Lo que los
separa de verdad es **la licencia y dónde viven los datos**, no la etapa.

Para este proyecto, LangSmith cubre todo lo que se usa, a costo cero y muy por
debajo de los límites del plan gratuito. Migrar exigiría tocar tres clientes,
el grafo, un endpoint, dos archivos de pruebas, la infra de dos nubes y dos
ADR, sin resolver ningún problema actual.

**Dónde Langfuse sí ganaría:** en un despliegue real en un banco. Ahí los datos
de transacciones no podrían salir de la red propia, y Langfuse se puede
autohospedar gratis (LangSmith sólo en Enterprise). Queda anotado como la
condición que reabriría la decisión.

## La premisa, contrastada

| Afirmación | Realidad |
|---|---|
| LangSmith es para desarrollo | Tiene monitoreo de producción, dashboards, alertas y evaluadores en línea. La API de lectura que usa `/api/v1/metrics/llm` es justamente un uso de producción. |
| Langfuse es para producción | También se usa en desarrollo (playground, datasets, experimentos). Es la misma categoría de producto. |
| La diferencia real | Langfuse es open source y se autohospeda sin licencia; LangSmith es SaaS propietario y su self-host requiere Enterprise. Langfuse es neutral al framework y nativo de OpenTelemetry; LangSmith está pensado primero para LangChain/LangGraph, aunque también acepta OTel. |

El origen probable de la idea: muchos equipos que no pueden mandar datos a un
SaaS de terceros eligen Langfuse autohospedado para producción. Es una razón de
cumplimiento, no de capacidad.

## Cómo se usa LangSmith hoy

| Pieza | Dónde | Qué hace |
|---|---|---|
| Trazado del grafo | `config/settings.py` (`propagar_langsmith`) | LangGraph traza solo cada nodo cuando hay `LANGSMITH_TRACING` en el entorno. Cero código en el grafo. |
| Trazado de los 3 clientes Anthropic | `arbiter/judge.py`, `explain/narrator.py`, `intel/searcher.py` | `wrap_anthropic`, con un `traceable` a mano en el árbitro que declara `usage_metadata`, proveedor y modelo (el arreglo del costo en $0, ADR-0019). |
| Costo y latencia en el dashboard | `api/routers/metrics.py` | `get_run_stats` (costo total, p50, p99, tokens, tasa de error) y `list_runs` agrupado por nodo, ventana de 3 días, caché de 30 s. |
| Pruebas | `tests/test_settings_langsmith.py`, `tests/test_api_metrics.py` | ~235 líneas que fijan ese comportamiento. |
| Infra y contrato | `infra/azure`, `infra/gcp`, contrato §1.4, ADR-0013, ADR-0019, diagrama C4 | Tres variables de entorno y un secreto compartido entre nubes (ADR-0023). |

**Volumen real:** 40 casos en 9 días desde la publicación, y entre 0 y 2 por
día después del pico. Con los experimentos incluidos, el proyecto está lejos de
las 5 000 trazas al mes del plan gratuito.

## Comparación para este caso

| Criterio | LangSmith (actual) | Langfuse Cloud | Langfuse autohospedado |
|---|---|---|---|
| Costo al volumen actual | USD 0 (Developer: 5k trazas base/mes, 1 usuario) | USD 0 (Hobby: 50k unidades/mes, 2 usuarios, sin tarjeta) | USD 0 de licencia, pero infra propia (ver abajo) |
| Unidad de cobro | Traza (1 por análisis) | Traza + cada observación + cada score (~15–25 unidades por análisis: 10 nodos más las llamadas LLM) | — |
| Capacidad gratis, en análisis/mes | ~5 000 | ~2 000–3 300 | Sin límite |
| Retención | 14 días (base) | 30 días | La que se configure |
| Trazado de LangGraph | Automático por variable de entorno | `CallbackHandler` pasado en el `config` de cada `astream`/`ainvoke` | Igual que Cloud |
| Trazado del SDK de Anthropic | `wrap_anthropic` oficial | Vía OpenTelemetry (`opentelemetry-instrumentation-anthropic`); el cálculo de costo por ese camino no está documentado | Igual que Cloud |
| Lectura agregada para el dashboard | `get_run_stats` trae p50, p99 y tasa de error en una llamada | Metrics API v2 (`/api/public/v2/metrics`); la doc muestra `sum` de `totalCost`, sin confirmar percentiles ni tasa de error | Igual (v4+) |
| Encaje con la observabilidad de infra (ADR-0024: Alloy, Tempo, OTel) | Separado | Nativo de OTel: podría recibir del mismo collector | Igual |
| Dónde viven los datos | SaaS de LangChain (EE. UU./UE) | AWS (EE. UU., UE o Japón) | Infra propia |
| Licencia | Propietaria | Open source; ClickHouse adquirió Langfuse en enero de 2026 y declaró que la licencia no cambia | Igual |

### Autohospedar no aplica a esta demo

Langfuse autohospedado necesita **seis componentes**: web, worker, PostgreSQL,
Redis, ClickHouse y almacenamiento S3. Docker Compose es sólo para uso local; en
producción piden Kubernetes. La demo hoy corre con una réplica en Container
Apps, Cloud Run que escala a cero y un Neon serverless de 0,25 CU. Sumar un
ClickHouse y un Redis siempre encendidos costaría más que todo el resto del
sistema junto, y el crédito de Azure tiene fecha.

## Qué costaría migrar

1. **Los tres clientes:** reemplazar `wrap_anthropic` por la instrumentación
   OTel de Anthropic o por `@observe`. Hay que rehacer el arreglo del árbitro:
   el bug del costo en $0 vino justamente de un camino que el wrapper no
   cubría, y habría que volver a verificarlo en vivo.
2. **El grafo:** pasar el `CallbackHandler` en `cases.py` (`astream`) y en
   cada entry point que invoque el grafo (scripts de evaluación incluidos).
   Hoy eso es implícito por entorno.
3. **Tarifas de modelos:** Langfuse calcula el costo con su tabla de modelos.
   Si un modelo nuevo (Sonnet 5, Haiku 5) no está en la tabla, el costo vuelve
   a dar $0 hasta cargar una definición propia. Mismo riesgo que ya pasó una vez.
4. **`/api/v1/metrics/llm`:** reescribirlo sobre la Metrics API v2, y confirmar
   que da p50, p99 y tasa de error. Si no los da, se calculan en Python
   bajando observaciones, que es lo que ADR-0019 midió como lento (93 s sin
   acotar).
5. **Pruebas, infra y documentos:** reescribir ~235 líneas de pruebas, cambiar
   variables y secretos en Terraform de las dos nubes, enmendar el contrato
   §1.4 y escribir un ADR que reemplace partes de ADR-0013 y ADR-0019. Además,
   regenerar el C4.
6. **Historia perdida:** las trazas de LangSmith no se migran. La evaluación de
   Jev y la de consistencia leyeron datos de producción de LangSmith.

Estimado: 1,5 a 2,5 días de trabajo, más la verificación en las dos nubes.

## Qué haría cambiar la decisión

- **Datos sensibles reales.** Si el sistema procesara transacciones reales, los
  prompts llevan montos, comercios y países del cliente. Eso exige que las
  trazas no salgan de la red propia → Langfuse autohospedado es la opción
  natural, porque no requiere licencia Enterprise.
- **Volumen.** Por encima de ~5 000 análisis al mes, LangSmith cobra por traza
  y por usuario. A ese volumen hay que comparar con números del proveedor;
  las comparaciones de terceros son modelos, no facturas.
- **Unificar observabilidad.** Si el stack OTel de ADR-0024 pasara de local a
  producción, Langfuse podría recibir trazas del mismo collector y juntar LLM e
  infra en un solo lugar.
- **Precios de LangSmith.** Varias fuentes de terceros reportan un aumento a
  mediados de 2026 (trazas base de USD 2,50 a 5,00 por 1 000 y retención
  extendida de 400 a 180 días). La página oficial no publica el precio por
  traza adicional, así que no está confirmado. Al volumen actual no importa.

## Si se quiere el aprendizaje sin el riesgo

Hay una opción de bajo costo, para portafolio o entrevista: **probar Langfuse en
paralelo y sólo en local**. Se suma al `observability/compose.observability.yml`
o a una cuenta Hobby, se trazan unas corridas de `scripts/` con
`CallbackHandler` y se compara con LangSmith: árbol de nodos, costo por nodo,
y si la Metrics API alcanza para el dashboard. No toca producción ni los
gates. Si se hace, merece su propio ADR antes de empezar, como pide el
proyecto.

## Fuentes

- [Precios de LangSmith (oficial)](https://www.langchain.com/pricing)
- [Precios de Langfuse (oficial)](https://langfuse.com/pricing)
- [Langfuse: autohospedaje](https://langfuse.com/self-hosting)
- [Langfuse: integración con Anthropic](https://langfuse.com/integrations/model-providers/anthropic)
- [Langfuse: Metrics API](https://langfuse.com/docs/metrics/features/metrics-api)
- [Langfuse: LangChain y LangGraph](https://langfuse.com/docs/langchain)
- Terceros, de forma orientativa: [DataCamp](https://www.datacamp.com/blog/langfuse-vs-langsmith),
  [Mastra](https://mastra.ai/articles/langfuse-vs-langsmith),
  [ZenML, precios de LangSmith](https://www.zenml.io/blog/langsmith-pricing),
  [CostBench](https://www.costbench.com/software/ai-observability/langsmith/)
