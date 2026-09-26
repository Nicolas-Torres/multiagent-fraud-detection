# ADR-0025: la demo pública se protege del abuso sin autenticación

- **Estado**: aceptado
- **Fecha**: 2026-09-25

## Contexto

Las dos demos (Azure y GCP) son públicas y la API no tiene autenticación
(acta 09 §6.1). Antes de difundirlas, una evaluación encontró que:

- `POST /api/v1/cases` corre el grafo completo con LLM (~USD 0.049 por
  ejecución, medido en LangSmith) **sin límite** para cualquier `transaction_id`
  que no tenga el prefijo `LIVE-`. El cooldown existente (acta 10 §3.5) sólo
  cubre los escenarios que arma el dashboard. Un script podría gastar
  ~USD 175 por hora hasta agotar el saldo de Anthropic, y dejar la demo
  degradada para todos, como en el incidente 0001.
- `/docs` y `/openapi.json` responden en producción: un formulario listo para
  hacer exactamente eso.
- `POST /cases/{id}/resolution` permite escribir texto que ven los demás
  visitantes.

Las dos nubes comparten la misma base (Neon) y el mismo saldo del proveedor.

## Decisión

**Un techo global de uso, contado en la base y activo sólo en producción,
y la API no se autodocumenta en producción.**

- `api/limites_demo.py`: como máximo **40 ejecuciones del grafo por hora y 200
  por día**, y **20 resoluciones por hora**, sumando las dos nubes. El conteo es
  una consulta sobre `cases.created_at` y `human_resolutions.resolved_at`. Al
  superarlo, `429` con el motivo, que el dashboard muestra tal cual.
- El techo corre **después** de la idempotencia: repetir un `transaction_id`
  no corre el grafo, así que no cuenta ni se bloquea.
- Los límites viven en código, como `LIVE_COOLDOWN`: iguales en las dos nubes
  sin configurar nada.
- En producción, `docs_url`, `redoc_url` y `openapi_url` son `None`. Los tipos
  del dashboard se generan con `app.openapi()` en proceso
  (`scripts/export_openapi.py`), así que no dependen de esas rutas.
- El cooldown por escenario se mantiene: resuelve el doble clic sobre el mismo
  escenario; el techo global cubre todo lo demás.

## Alternativas descartadas

**Techo en memoria del proceso.** Más simple y sin consultas. Se descarta porque
habría uno por nube —el doble de gasto posible sobre el mismo saldo— y se
reiniciaría con cada deploy o caída del contenedor.

**Límite por IP.** Es la forma habitual de rate limiting. Se descarta porque sin
sesiones la IP es fácil de rotar, y detrás del ingress de cada nube la IP real
llega en cabeceras que habría que confiar. Protege peor el costo, que es lo que
importa.

**Autenticación.** Resolvería el problema de raíz, pero cambia la naturaleza de
la demo: quien llega desde el README o una publicación tiene que poder probarla
sin registrarse.

**Techo en la configuración de cada proveedor** (límite de gasto de Anthropic,
presupuestos de nube). Se usa como red de seguridad, no como mecanismo
principal: cuando se alcanza, la demo queda degradada para todos y sin un
mensaje que lo explique.

## Consecuencias

**Se gana** un techo de gasto conocido: ~USD 10 por día en el peor caso, contra
un gasto sin límite. Un visitante real nunca lo alcanza: cada escenario ya tiene
su propio cooldown.

**Se paga**:

- Una consulta de conteo más por cada caso nuevo o resolución. Es despreciable
  para Neon, pero es una consulta más en el camino de escritura.
- **Es un techo blando**: dos requests simultáneos pueden pasarlo por uno o dos.
  Se acepta: protege un presupuesto, no una cuota contractual.
- Un pico legítimo de visitas —por ejemplo, el día que se difunde la demo—
  puede encontrar el techo agotado. El mensaje lo explica.
- En producción ya no hay Swagger para explorar la API. El contrato sigue
  documentado en `docs/contrato_de_interfaz.md`, y en local `/docs` funciona
  igual.
- La cuota gratuita de Neon sigue siendo un techo aparte: si se agota, las dos
  demos se caen hasta el mes siguiente. Este ADR no lo resuelve.
