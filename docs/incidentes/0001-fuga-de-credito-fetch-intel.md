# Incidente 0001 — fuga de crédito Anthropic vía `fetch-intel`

**Fecha del incidente**: 2026-09-07 a 2026-09-13. **Detectado**: 2026-09-14,
por el usuario (agotamiento de saldo, no por alerta del sistema).
**Impacto**: ~USD 20 de crédito de la API de Anthropic consumidos sin
ningún resultado útil — cero snapshots de inteligencia externa quedaron
persistidos en los 6 días que el bug estuvo activo con crédito disponible.

## Síntoma

El 2026-09-07 se cargó USD 20 de crédito a la cuenta de Anthropic. El
2026-09-13 ya estaba agotado. La consola de Anthropic mostraba gasto
diario en `claude-sonnet-4-6` — el modelo que
`src/multiagent_fraud_detection/intel/snapshot.py:17` designa
exclusivamente para `scripts/fetch_threat_intel.py` (ADR-0014). El
dashboard, aparte, mostraba el mensaje de degradación "Evidencia
incompleta" en cada transacción evaluada en ese período — consecuencia,
no causa: sin snapshot fresco y sin crédito, el nodo
`external_threat_intel` y el resto del grafo quedaban degradados.

## Causa raíz

Dos bugs independientes que se combinan. **La frontera de ADR-0014 sigue
intacta** — en runtime, `external_threat_intel` sólo hace *lookup* sobre
Postgres, nunca toca la red; esto no es una violación arquitectónica, es
desperdicio operacional dentro del propio script de build.

### Bug 1 — sesión de DB abierta durante todo el loop de búsquedas

`scripts/fetch_threat_intel.py` (antes del fix) abría una única sesión al
principio de `_correr()`, la usaba para leer `emisores`/`allowlist`, y
reutilizaba esa misma sesión —todavía abierta— para el `_upsert` final,
después de que el loop de búsquedas (15 emisores × `claude-sonnet-4-6` +
`web_search`, 7 a 10 minutos reales) terminara. Neon (Postgres serverless)
mata las transacciones idle antes de esos 7-10 minutos, así que el
`_upsert` fallaba siempre con:

```
psycopg.errors.IdleInTransactionSessionTimeout: terminating connection due to idle-in-transaction timeout
```

**El 100% de las corridas fallaba en el último paso — nunca se guardó una
fila.**

### Bug 2 — reintento automático duplicaba el costo

`infra/azure/main.tf` tenía `azurerm_container_app_job.fetch_intel` con
`replica_retry_limit = 1`. Cada falla del bug 1 disparaba un reintento
automático de Azure Container Apps, que repetía el loop completo de 15
emisores desde cero — pagándolo una segunda vez, con el mismo desenlace.

## Evidencia (Azure Log Analytics, `ContainerAppConsoleLogs_CL`)

Se confirmó vía `az monitor log-analytics query` sobre el workspace
`log-fraud-detection` (los logs de un Container Apps *Job* no llevan
`ContainerAppName_s`, a diferencia de la app principal — hay que filtrar
por ese campo vacío). Dos arranques del loop por día, 7 a 10 minutos
aparte, los 6 días que hubo crédito:

```
2026-09-07  06:00:17  "15 emisores..."  →  falla ~6 min después
            06:06:52  "15 emisores..."  →  falla ~7 min después  (reintento)
2026-09-08  06:00:25  ...               →  falla 9.5 min después
            06:10:22  ...               →  falla igual           (reintento)
2026-09-09 .. 2026-09-12: mismo patrón, dos corridas por día
2026-09-13  06:00:19  "15 emisores..."  →  falla instantáneo (sin crédito, HTTP 400, no se cobra)
            06:02:20  "15 emisores..."  →  falla instantáneo (reintento, tampoco se cobra)
```

Total real: **12 corridas completas y pagadas** (6 días × 2 intentos),
cero snapshots persistidos. El 13, sin crédito, ambos intentos fallaron
gratis con `anthropic.BadRequestError: 400 — Your credit balance is too
low` (rechazado antes de generar nada) — coincide con la caída brusca de
gasto que se ve en la captura de "Uso" de ese día.

## Fix

1. **`scripts/fetch_threat_intel.py`**: se separó la sesión de lectura
   (`emisores`/`allowlist`, cerrada antes del loop) de una sesión nueva
   abierta recién antes de `_upsert`/`commit`, para que ninguna
   transacción quede abierta mientras corren las búsquedas. Verificado
   con `--fake` dos veces seguidas (idempotencia intacta, 15 filas
   ambas corridas) y con la suite completa (`uv run pytest`, sin
   regresiones).
2. **`infra/azure/main.tf`**: `replica_retry_limit = 0` en
   `azurerm_container_app_job.fetch_intel` — mismo criterio que ya
   aplica el job de migración (ADR-0009): un reintento automático no
   arregla un bug de código, sólo paga la misma falla dos veces.
   Aplicado con `terraform apply` real; verificado post-apply con
   `az containerapp job show --query "properties.configuration.replicaRetryLimit"`
   → `0`.

GCP no se tocó: su Cloud Scheduler nunca llegó a disparar ninguna
ejecución del job equivalente (bug separado, ya detectado, costo real
$0). Aplicarle el mismo `replica_retry_limit`/patrón de sesión queda
pendiente para cuando se resuelva ese otro bug.

## Aprendizaje operacional — manejo de secretos en esta sesión

Durante la investigación y el fix, dos secretos (`ghcr_token` primero, y
luego el set completo pasado por `-var` en un comando `! terraform
plan ...`) quedaron expuestos en texto plano en la conversación: uno por
imprimir el resultado de `az containerapp secret show` sin canalizarlo
a su consumidor, y el otro porque un comando `!` corrido por el usuario
también queda completo (input y output) en la conversación — no es un
canal oculto. Los cuatro secretos involucrados (`ghcr_token`,
`database_url`, `anthropic_api_key`, `gemini_api_key`) se rotaron.

Desde ahora, `infra/azure/` usa `terraform.tfvars` (gitignored,
`infra/**/*.tfvars`) en vez de `-var` en la línea de comandos —
`terraform.tfvars.example` documenta las claves sin valores reales. El
archivo real se edita a mano con un editor de texto, nunca se tipea en
el chat ni en un comando `!`.

## Pendiente

- Alertar sobre gasto/errores del job `fetch-intel` en vez de depender
  de que alguien note el saldo agotado — no se abordó en este incidente,
  queda para una mejora aparte.
- Aplicar el mismo `replica_retry_limit = 0` al lado GCP cuando se
  resuelva el bug de Cloud Scheduler (`NOT_FOUND`, código 5).
