# Incidente 0005 — el readiness probe de Azure mantenía despierto el compute de Neon

**Fecha de la investigación**: 2026-09-19/20. Disparado por un mail
automático de Neon: el proyecto `pg-fraud-detection` llegó al 80% (80 de
100 CU-hours) de su asignación mensual gratuita **sin haber pasado ni un
mes** desde el primer deploy (2026-09-06/07).

## Síntoma

80 CU-hours consumidas en ~13 días, sin que el usuario haya generado un
volumen de tráfico que lo explicara — la sospecha inicial fue "¿hay un bug
o un bucle consumiendo la base?".

## Causa real

`GET /ready` (`src/multiagent_fraud_detection/api/app.py`) hace un
`SELECT 1` real contra Postgres en cada llamada — por diseño, para que un
probe de infraestructura detecte una caída real (ver el propio docstring
del endpoint). El problema no es esa lógica en sí, es la frecuencia con la
que se dispara: confirmado con logs reales de
`ContainerAppConsoleLogs_CL`, el `readiness_probe` de Azure Container Apps
(`infra/azure/main.tf`, sin `interval_seconds` propio → usa el default de
la plataforma) golpea `/ready` **cada 10 segundos, las 24 horas**, desde
que el Container App quedó arriba — consistente con `min_replicas = 1`
(ADR-0021: siempre encendido, "se paga para que nadie encuentre el sistema
dormido").

Eso nunca le da a Neon un hueco de inactividad para autosuspender su
compute serverless — cada `SELECT 1` cada 10s reinicia el contador de
inactividad antes de que se acumule suficiente tiempo idle. La matemática
lo confirma casi exacto:

```
80 CU-hours ÷ (13 días × 24h) ≈ 0.256 CU
```

Prácticamente el compute mínimo de Neon (0.25 CU), activo el 100% del
tiempo desde el primer deploy. Proyectado a un mes completo:
**0.25 × 24 × 30 = 180 CU-hours** — 80 por encima de las 100 gratis,
**todos los meses, indefinidamente**, si no se tocaba nada.

## Lo que no hacía falta construir

Neon Postgres serverless ya autosuspende por inactividad y despierta solo,
de forma transparente, en la primera conexión nueva (cold-start de bajo un
segundo) — no hace falta orquestar "activar el compute a demanda", eso ya
es su comportamiento nativo. El único obstáculo era que el propio probe
nunca dejaba pasar el hueco de inactividad necesario para que ese
mecanismo se activara.

## Opciones evaluadas

| Intervalo de chequeo real | % del tiempo despierto (autosuspend ≈5min, supuesto a confirmar en la config de Neon) | CU-hours/mes | ¿Entra en las 100 gratis? |
|---|---|---|---|
| 10s (el que había) | 100% | 180 | No |
| 15 min | ~33% | ~60 | Sí, con margen |
| 30 min | ~17% | ~30 | Sí, con bastante margen |
| **60 min (elegido)** | ~8% | **~15** | Sí, sobra mucho |

Se eligió **60 minutos** en vez de un valor más corto (15-30 min) por una
razón específica de esta infraestructura, no sólo por ahorro: con
`min_replicas = 1` (una sola réplica), el readiness probe no puede hacer
*failover* real — no hay otra réplica sana a la que Azure le enrute
tráfico en su lugar. Su único valor con una sola réplica es dejar de
aceptar tráfico que se sabe que va a fallar, no alta disponibilidad. El
caso histórico real de esta clase (incidente 0002, credenciales
desactualizadas) lo sigue cubriendo el chequeo real que corre en **cada
contenedor nuevo al arrancar** (el caché arranca vacío); el stack de
observabilidad (ADR-0024, Grafana/Loki/Tempo) es la red de respaldo para
lo que pase entre medio. El costo real de elegir 60 min en vez de un valor
más corto es que la primera visita después de un hueco largo sin tráfico
paga el cold-start de Neon (bajo un segundo) — insignificante para un
proyecto de portafolio.

## Fix

`src/multiagent_fraud_detection/api/app.py`, endpoint `/ready`:

- Un contenedor recién arrancado no tiene nada cacheado todavía, así que
  su primera llamada siempre hace el `SELECT 1` real.
- En régimen: si el último chequeo real fue exitoso hace menos de
  `READY_CACHE_MINUTES` (60), responde `200` sin tocar Postgres. Si venció
  la ventana, o el último chequeo fue un fallo, vuelve a chequear de
  verdad.
- **Un fallo nunca se cachea** — la siguiente llamada intenta de nuevo, no
  espera a que venza la hora.
- Gateado por `settings.environment == "production"` (mismo criterio que
  `metrics_router.precalentar()`): en test/local cada llamada sigue
  chequeando siempre, sin lo cual dos tests de la misma suite (éxito y
  fallo de `/ready`) competirían por el mismo caché global.

## Verificación

- `uv run pytest`: 309 passed — `tests/test_api_health.py` sin cambios,
  el gate por `environment` deja intacto el comportamiento en test.
- No se verificó contra Neon real en esta pasada (implicaría desplegar y
  esperar horas para ver el efecto en CU-hours) — el próximo repaso del
  costo en la consola de Neon, unos días después del deploy, es la
  confirmación de facto.

## Pendiente

- Confirmar en la configuración real del proyecto en Neon cuál es el
  timeout de autosuspend exacto (se asumió ~5 minutos, el valor típico) —
  no cambia la conclusión, pero ajustaría el número fino de la tabla de
  arriba.
- El mismo patrón (readiness probe DB-touching, sin costo por el lado de
  GCP porque `min_instance_count = 0` ya escala a cero) no aplica a GCP —
  confirmado, no hace falta el mismo fix ahí.
