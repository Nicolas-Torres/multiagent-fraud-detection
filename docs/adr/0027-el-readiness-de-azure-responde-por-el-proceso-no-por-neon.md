# ADR-0027: el readiness de Azure responde por el proceso, no por Neon

- **Estado**: aceptado
- **Fecha**: 2026-09-29

## Contexto

El readiness probe de la Container App llamaba a `/ready` cada 10 s, y `/ready`
hace `SELECT 1` contra Neon. El incidente 0005 le puso un caché de 60 minutos,
pero el probe siguió despertando a Neon una vez por hora:

- **Costo:** ~15 CU-h al mes sin ninguna visita, de una cuota gratuita de 100.
  El monitoreo de Neon muestra un pico de actividad por hora.
- **Disponibilidad:** el probe tiene un timeout de 1 s. Cuando la consulta de
  cada hora encuentra a Neon dormido, despertarlo tarda más, el probe falla y
  Azure deja la única réplica sin tráfico hasta 3 éxitos seguidos, unos 30 s.
  Pasó el 29/09 a las 04:15 y 06:16 UTC (`ReplicaUnhealthy … Client.Timeout
  exceeded`).

Un readiness probe responde a "¿esta réplica puede atender?". Con una
dependencia compartida por todas las réplicas, como la base, marcarlas no
disponibles cuando la base falla no arregla nada: sólo suma un corte al error.

## Decisión

**El readiness probe de Azure apunta a `/health`, que no hace I/O. `/ready`
sigue significando "Postgres responde", sin caché.**

- `/health` es liveness y readiness de Azure.
- `/ready` queda para diagnóstico manual, `scripts/smoke_api.py` y el startup
  probe de GCP, que corre una vez por arranque de instancia. **Nunca para un
  probe periódico.** Como ya nadie lo llama cada 10 s, el caché del incidente
  0005 sobra: cada llamada consulta la base y dice la verdad en ese momento.
- El cambio del probe se aplicó primero por CLI (revisión `--0000026`) y
  después se sincronizó en Terraform. Si se hacía al revés, `/ready` sin caché
  con el probe todavía apuntando ahí habría consultado Neon cada 10 s.

## Alternativas descartadas

**Subir el caché a 6 horas.** Baja el costo, pero Neon sigue despertando, y los
cortes de ~30 s siguen pasando, sólo que menos seguido.

**Cambiar lo que significa `/ready`** para que no toque la base. Rompe el
contrato (§1.3) y a sus cuatro consumidores, que esperan un chequeo de Postgres.

**`min_replicas = 0` en Azure.** Sin réplica ociosa no hay probe, pero cada
visita después de un rato sin tráfico paga un arranque en frío.

**Subir el timeout del probe.** Evita los cortes, pero no el costo.

## Consecuencias

**Se gana**:

- Neon sólo despierta por visitas reales, deploys y el fetch-intel semanal. El
  consumo base pasa de ~15 CU-h al mes a ~0.
- No más cortes por arranque en frío de la base.
- `/ready` responde por el estado real de la base, sin memoria.

**Se paga**:

- Si Neon se cae, Azure no se entera por el probe: la réplica sigue recibiendo
  tráfico y los endpoints que usan la base responden 5xx. Es el comportamiento
  buscado: un error explícito de la API es más fácil de diagnosticar que una
  réplica marcada no disponible. La vigilancia de la base queda del lado del
  monitoreo (logs de 5xx, consola de Neon), no del probe.
