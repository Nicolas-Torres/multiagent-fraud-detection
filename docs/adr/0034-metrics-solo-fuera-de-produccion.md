# ADR-0034: `/metrics` sólo fuera de producción

- **Estado**: aceptado
- **Fecha**: 2026-10-06
- **Actualiza**: ADR-0024 (`GET /metrics` deja de ser parte de la API pública).

## Contexto

ADR-0024 sumó métricas HTTP en formato Prometheus (`GET /metrics`) para el stack
de observabilidad local: Alloy las lee desde `localhost` y Grafana las muestra. El
mismo ADR declaró que ese backend corre "sólo en `docker compose`, sólo local".

El endpoint, en cambio, se registraba en todos los entornos, y respondía público y
sin autenticación en Azure y GCP. Revisado el 2026-10-06, expone 20 familias de
métricas: memoria, CPU y hora de arranque del proceso, la versión de Python, y la
cantidad, latencia y tamaño de los pedidos por ruta (como plantilla:
`/api/v1/cases/{case_id}`).

No expone claves, datos de casos, IPs ni nada personal; las rutas y la versión de
Python ya son públicas en el repositorio. El riesgo es bajo. Pero nadie lo lee en
producción, y en GCP sus contadores se reinician con cada arranque en frío:
mostrar el uso y la carga de la API no aporta nada.

## Decisión

Con `ENVIRONMENT=production`, el instrumentador **no se registra**: no se expone
`/metrics` y tampoco se acumulan contadores en memoria. Es la misma condición que
ya apaga `/docs`, `/redoc` y `/openapi.json` (ADR-0025).

En producción, `GET /metrics` cae al catch-all del dashboard, como cualquier otra
ruta desconocida fuera de `/api/`. En local nada cambia.

## Alternativas descartadas

**Instrumentar sin exponer.** Deja contadores en memoria que nadie consulta.

**Un `404` explícito en `/metrics`.** Exige registrar una ruta sólo para decir que
no existe, y ningún scraper apunta ahí.

**Protegerlo con autenticación.** Sería la opción si un Prometheus en la nube lo
leyera. Hoy no existe ese consumidor (la pregunta de producción de ADR-0024 sigue
abierta), así que es complejidad sin uso.

## Consecuencias

**Se gana**: la API pública expone sólo lo que el dashboard usa.

**Se paga**: si algún día se lleva el stack de observabilidad a la nube, habrá que
volver a exponer las métricas, esta vez con autenticación o en una red privada.
