# ADR-0029: fetch-intel a demanda, sin cron

- **Estado**: aceptado
- **Fecha**: 2026-10-01
- **Actualiza**: ADR-0026 (la cadencia semanal pasa a "a demanda"; el modelo y el
  tope de salida no cambian) y ADR-0022 (Cloud Scheduler queda en pausa).

## Contexto

`fetch-intel` llena `threat_indicators`. Corría cada lunes en las dos nubes
(ADR-0026), contra **la misma base**: la de Azure escribía y la de GCP repetía el
trabajo. La de GCP en realidad nunca corrió. Su Cloud Scheduler llamaba a
`cloudrun.googleapis.com`, que no existe, con un token OIDC. Una API de Google
(`*.googleapis.com`) pide OAuth. Fallaba con `404` desde el 2026-09-07; el
incidente 0001 ya lo había anotado como pendiente.

Lo que el snapshot aporta a la demo no depende de su frescura:

- El lookup trae todos los indicadores de la `SNAPSHOT_VERSION` vigente. No hay
  control de antigüedad.
- FP-10 compara contra la fecha de la transacción, y las de la demo son de
  diciembre de 2025. Un indicador de hoy no la dispara (ADR-0015).
- El corpus casi no deja filas: las fuentes llegan sin fecha legible y se
  descartan (incidente 0010, acta 13 §5). La corrida de prueba de este ADR dejó
  0 filas sobre 130 resultados.

Un cron semanal pagaba ~USD 0.28 por corrida, en cada nube, sin cambiar ninguna
decisión.

## Decisión

`fetch-intel` corre **a demanda**, en las dos nubes:

- **Azure**: el job pasa de `schedule_trigger_config` a `manual_trigger_config`.
  Se corre con `az containerapp job start -n caj-fraud-detection-fetch-intel -g rg-fraud-detection`.
- **GCP**: se corrigen la URI (`run.googleapis.com`) y el token (`oauth_token`),
  y el scheduler queda con `paused = true`. Para correrlo:
  `gcloud run jobs execute fraud-detection-fetch-intel --region us-central1`.
- `max_retries = 0` en GCP, igual que `replica_retry_limit = 0` en Azure
  (incidente 0001).

Se corre a mano cuando cambia `SNAPSHOT_VERSION` (otro modelo o prompt), porque
el lookup filtra por versión exacta y la tabla queda vacía para la versión nueva.

## Alternativas descartadas

**Semanal en una sola nube.** Mantiene el pipeline "vivo", pero paga ~USD 1.2 al
mes por un corpus que no cambia ninguna decisión.

**Corregido y activo en las dos.** Duplica el gasto sobre la misma base y deja
dos escrituras concurrentes el mismo lunes.

**Borrar el scheduler de GCP.** Ahorra un recurso, pero pierde la prueba de que el
camino scheduler → job funciona. Pausado cuesta lo mismo: nada.

## Consecuencias

**Se gana**: cero gasto recurrente de fetch-intel, y el Terraform de GCP deja de
describir un cron que no corría.

**Se paga**:

- Un despliegue real con FP-10 activa necesitaría volver a una cadencia acorde a
  su ventana de 24 h. Es la misma salvedad de ADR-0026, ahora más fuerte.
- Reanudar el scheduler de GCP desde la consola lo deja corriendo hasta el
  próximo `terraform apply`, que lo vuelve a pausar.

**Verificado** (2026-10-01): el scheduler corregido respondió `200` y la
ejecución `fraud-detection-fetch-intel-f8hv9` terminó con `exit(0)`. El job de
Azure quedó en `Manual` con 0 reintentos.
