# Incidente 0004 — costo elevado de `claude-sonnet-4-6` por `MAX_USES=3`

**Fecha de la investigación**: 2026-09-17. **No es un incidente de
seguridad ni de disponibilidad** — es una investigación de costo a pedido
del usuario, que terminó en un fix real de configuración, no de código
roto.

## Síntoma

En la consola de Anthropic, agrupando por modelo, `claude-sonnet-4-6`
mostraba un costo diario mucho mayor que `claude-sonnet-5` — por ejemplo,
2026-09-16: **USD 1.56 vs USD 0.07**, ~22x, pese a que `claude-sonnet-4-6`
lo usa un solo punto del sistema
(`src/multiagent_fraud_detection/intel/snapshot.py:17`,
`MODEL = "claude-sonnet-4-6"`, consumido sólo por
`scripts/fetch_threat_intel.py` vía `AnthropicSearcher`).

## Se descartó, con datos, lo que no era

- **¿El bucle del incidente 0001 volvió?** No. `ContainerAppConsoleLogs_CL`
  confirma **una sola ejecución diaria** de `caj-fraud-detection-fetch-intel`
  desde el 2026-09-15 (06:00:19, 06:00:23, 06:00:19 en los tres días
  siguientes) — el `replica_retry_limit=0` de ese incidente sigue vigente.
  Antes del fix (7-13 sept) sí había dos corridas por día, pero ese costo
  ya se pagó y no es lo que explica el patrón reciente.
- **¿GCP también lo está corriendo, duplicando el gasto entre nubes?** No.
  `gcloud scheduler jobs list` muestra el cron `fraud-detection-fetch-intel-cron`
  activo, pero `gcloud run jobs executions list --job=fraud-detection-fetch-intel`
  devuelve **cero ejecuciones históricas** — el trigger de Cloud Scheduler
  hacia Cloud Run Jobs nunca funcionó (bug ya anotado, separado, costo
  real $0).

## La causa real

`src/multiagent_fraud_detection/intel/searcher.py:33` —
`MAX_USES = 3`, pasado como `max_uses` a la herramienta `web_search` de la
API (línea 116 de ese archivo). Por cada uno de los 15 emisores del
dataset, el modelo puede disparar **hasta 3 búsquedas** antes de
responder — un loop agéntico de herramienta, no una llamada de una sola
vez. Una corrida completa son hasta 15 × 3 = **45 búsquedas**, no 15.

Los números de la consola cuadran con eso: "Costo total de búsqueda web"
de la ventana ≈ USD 1.27, que a la tarifa pública histórica de ~USD 0.01
por búsqueda son ~127 búsquedas. Repartidas entre las corridas limpias de
una ejecución diaria (15, 16, 17 sept), da ~42 búsquedas por corrida —
muy cerca del techo de 45: casi todos los emisores estaban agotando las 3
búsquedas permitidas, no usando 1 y listo.

`claude-sonnet-5` no tiene ninguno de estos tres factores: corre sólo
cuando el usuario dispara una transacción real (esporádico, no
automático), sin herramienta `web_search` (sin su cargo por uso aparte de
tokens), y en una sola llamada de ida y vuelta con prompt fijo (sin
rondas que acumulen contexto).

## Fix

`MAX_USES` de 3 a 1. La query
(`"Alertas públicas de fraude, phishing o compromiso de seguridad sobre
el banco emisor {issuer_bank} en Perú."`, `intel/snapshot.py:30-33`) es
una búsqueda puntual y específica, no una pregunta abierta que necesite
refinamiento iterativo — no hay razón de negocio para pagar hasta 3
rondas por emisor.

No cambia ningún comportamiento observable del pipeline: mismo
`SNAPSHOT_VERSION`, misma `GENERATION` (ADR-0014 exige subir `GENERATION`
sólo cuando cambia qué se pregunta o qué modelo responde, no cuántas
veces puede reintentar internamente la misma pregunta), y el allowlist +
`parse_page_age` siguen filtrando exactamente igual sobre lo que vuelva.

## Verificación

- `uv run pytest`: `tests/test_searcher.py` prueba el parseo de
  `_extraer`/`parse_page_age` con dobles, sin red — no depende del valor
  de `MAX_USES`, sigue en verde.
- No se corrió `fetch_threat_intel.py` real como parte de esta
  verificación, para no gastar cuota confirmando un cambio que de por sí
  reduce gasto — el cron diario de mañana (06:00 UTC) es la confirmación
  de facto; se puede revisar el costo del día siguiente en la consola.

## Pendiente

- Confirmar con el costo real de un día completo post-fix que el gasto de
  `claude-sonnet-4-6` bajó proporcionalmente (esperado: cerca de 1/3 del
  actual, ya que la reducción de `MAX_USES` afecta tanto el cargo de
  `web_search` como los tokens de las rondas que ya no ocurren).
- El trigger de Cloud Scheduler → Cloud Run Jobs en GCP sigue roto (0
  ejecuciones desde que existe) — bug ya conocido y documentado aparte,
  costo real $0, no se aborda en esta pasada.
