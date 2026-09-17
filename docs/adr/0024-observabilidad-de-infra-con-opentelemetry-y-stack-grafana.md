# ADR-0024: la observabilidad de infraestructura se instrumenta con OpenTelemetry y se sirve con un stack Grafana local

- **Estado**: aceptado
- **Fecha**: 2026-09-16

## Contexto

La app hoy no tiene ninguna instrumentación de infraestructura: logging sin
estructurar (`logging.getLogger` en dos archivos, sin configuración
propia), sin métricas Prometheus, sin trazas OpenTelemetry — cero
dependencias de ese tipo en `pyproject.toml`.

LangSmith (ADR-0019) cubre lo específico de LLM: costo y latencia por nodo
del grafo. `api/routers/metrics.py` declara explícitamente que no quiere
ser una segunda fuente de verdad para eso. Pero no cubre la otra mitad del
sistema: latencia real de cada endpoint HTTP, tasa de error, ni cuánto
tarda una query contra Postgres. Hoy esa mitad es invisible salvo que se
mire Log Analytics/Cloud Logging a mano, como se hizo para investigar los
incidentes 0001-0003.

Restricción real de este proyecto, ya puesta a prueba una vez: **el costo
fijo mensual importa**. ADR-0021 rechazó AKS explícitamente por su "piso de
costo fijo mensual — del orden de varias decenas de dólares sólo por el
clúster". Un stack de observabilidad self-hosted en la nube (Loki + Tempo +
Prometheus + Grafana, todos con storage persistente y al menos uno de ellos
corriendo 24/7) tiene la misma forma de gasto — no se puede decidir a la
ligera, y no hace falta decidirlo todavía para empezar a sacarle valor al
stack.

## Decisión

Se instrumenta la app con **OpenTelemetry como capa única** para trazas y
logs (auto-instrumentación de FastAPI y SQLAlchemy, sin tocar
`graph/nodes.py` ni los routers) más `prometheus-fastapi-instrumentator`
para métricas HTTP en `GET /metrics`. Todo se envía a un único collector,
**Grafana Alloy**, que reenvía trazas a Tempo, logs a Loki y métricas
(scrape de `/metrics`) a Prometheus vía `remote_write`. Grafana los sirve
con los tres datasources correlacionados por `trace_id` (traza↔logs).

El backend completo (Alloy, Loki, Tempo, Prometheus, Grafana) corre **sólo
en `docker compose`, sólo local**. No se toca Terraform, Azure ni GCP en
esta pasada — se decide deliberadamente no resolver la pregunta de
Grafana Cloud vs. self-hosted en producción hasta tener el stack probado
localmente y una razón real para pagar por él.

LangSmith no se duplica ni se reemplaza: sigue siendo la única fuente para
costo/latencia de LLM.

## Alternativas descartadas

**`structlog` + cliente Loki directo + tracer OTel por separado.** Tres
piezas distintas para tres señales que, en el mundo OTel, ya vienen
unificadas por diseño (logs con `trace_id`/`span_id` inyectados
automáticamente si el SDK de trazas ya está inicializado). Mantener
`logging` estándar con un `LoggingHandler` de OTel agregado da la misma
correlación con un diff mucho menor — no hay que tocar los call sites
existentes.

**Conectar la app directo a Loki/Tempo/Prometheus, sin Alloy.** Funciona,
pero la app tendría que conocer tres endpoints y tres protocolos distintos
en vez de uno (OTLP) y un scrape. Un solo collector también es el punto
natural para, más adelante, filtrar/samplear antes de pagar por Grafana
Cloud si esta pasada se lleva a producción.

**Resolver ya mismo Azure/GCP (Grafana Cloud o self-hosted).** Es la
decisión más cara y la que menos hace falta tomar hoy — local ya da valor
real (ver una traza real con sus queries, correlacionarla con sus logs) sin
comprometer ni un dólar. Se pospone a propósito, no se descarta.

## Consecuencias

**Se gana**: visibilidad real de HTTP/DB que hoy no existe, sin tocar
LangSmith ni el código de los nodos del grafo, con logs y trazas
correlacionados automáticamente — algo que Log Analytics/Cloud Logging por
separado no dan.

**Se paga**:

- Seis servicios más en el `docker compose` local (aunque en un archivo de
  override separado, para no pesarle a quien sólo necesita Postgres).
- Ninguna de las trazas cubre hoy los nodos internos del grafo LangGraph
  (`decision_arbiter`, `evidence_aggregation`, etc.) — sólo el borde
  HTTP/DB. Instrumentarlos manualmente queda pendiente.
- La pregunta de producción (dónde vive Loki/Tempo/Prometheus/Grafana
  cuando esto se lleva a Azure/GCP) queda abierta — este ADR resuelve la
  instrumentación, no el despliegue.
