# Incidente 0013 — clave de Anthropic vencida, y una rotación que no llegó a todos lados

**Fecha**: 2026-10-14 (primer error registrado) al 2026-10-15 (resuelto).
**Detectado**: el 2026-10-15, en la evaluación del día 13 de la publicación en
LinkedIn. No hubo alerta del sistema.
**Impacto**: todo análisis terminaba en `ESCALATE_TO_HUMAN`, aunque debiera
aprobarse. Un visitante corrió 4 análisis el 14/10 entre 15:53 y 16:04 UTC y vio
los 4 escalados.

## Síntoma

En la lista de casos, los 4 del 14/10 estaban en `PENDING_HUMAN`, incluidos dos
escenarios que siempre se aprueban (CU-0426 y CU-0115). Los 4 tenían la misma
razón: "proveedor de juicio no disponible: se escala con el piso
deterministico", y ninguno llevaba `arbiter_prompt_version` ni
`explanation_prompt_version`. En los logs de Azure, cada llamada a Anthropic
devolvía `401 authentication_error: invalid x-api-key`.

## Causa raíz

**La clave venció.** Se había creado con fecha de vencimiento en la consola de
Anthropic, y nadie anotó esa fecha. La misma clave estaba en `.env` y en
`infra/shared.secrets.tfvars`, y también fallaba contra `GET /v1/models`, así que
no era un error de carga en una nube. Antes de confirmar el vencimiento se
descartó una filtración: la clave no aparece en el repo, en su historia ni en las
alertas de secret scanning de GitHub. El último caso sano es del 11/10 a las
15:35 UTC.

**El sistema degradó como fue diseñado, y eso ocultó la caída.** El debate cayó a
su respaldo y el árbitro escaló con el piso (ADR-0016): nunca aprobó de menos,
pero tampoco avisó. Sin tráfico, nadie lo habría notado.

## Fix

Se generó una clave nueva y se aplicó con `infra/rotate-secrets.sh`
(2026-10-15, ~09:23 UTC). La rotación destapó dos defectos del script:

1. **GCP: los jobs fallaron al actualizarse.** Al cambiar `secret_data`,
   Terraform reemplaza la versión del secreto, y por defecto destruye la vieja
   antes de crear la nueva. Los jobs `migrate`, `seed` y `fetch-intel` se
   actualizaron en ese intervalo, cuando `latest` apuntaba a la versión 3 ya
   `DESTROYED`, y quedaron con la condición en error. La API no se afectó: lee
   `latest` al arrancar cada instancia, y la primera prueba después de rotar
   salió `APPROVE`.
   **Arreglo:** `lifecycle { create_before_destroy = true }` en
   `google_secret_manager_secret_version` (`infra/gcp/main.tf`).
2. **Azure: la réplica siguió con la clave vieja.** Container Apps no reinicia
   las réplicas al cambiar un secreto, y la API corre siempre con una réplica
   (`min_replicas = 1`). La primera prueba después del apply volvió a dar 401;
   tras reiniciar la revisión activa, salió `APPROVE`.
   **Arreglo:** `rotate-secrets.sh apply` reinicia las revisiones activas de la
   API de Azure después de aplicar.

Verificado: un análisis de aprobación por nube, los dos `APPROVE` con el árbitro
sellado (`claude-sonnet-5:arbiter-verdict:3`).

## Lo que queda

- ~~Los jobs de GCP con la condición en error~~: los corrigió el deploy del
  PR #81 (`sha-2a00ff4`), que los actualizó con `gcloud run jobs update`.
- Los 4 casos del visitante y una corrida de verificación (`97ec38c0`) quedan en
  la cola HITL con un veredicto que no salió del árbitro. No se borran: borrar
  datos tiene sus propias consecuencias (incidentes 0003 y 0006).
- ~~La versión 2 del secreto en Secret Manager~~ (2026-09-15, fuera de
  Terraform): destruida el 2026-10-15.
- En GCP, una instancia que estuviera caliente al rotar seguiría con la clave
  vieja hasta reciclarse. Esta vez no la había; el script no lo fuerza.

## Aprendizaje

Una clave con vencimiento es un corte programado. Al crearla hay que anotar la
fecha y agendar la rotación antes; si no, el corte llega sin aviso, como acá.

Además, una degradación bien diseñada protege la decisión, pero también puede esconder
una caída completa del proveedor. Que el árbitro escale todo es correcto como
respuesta a un caso; como estado que dura días, es una alerta que nadie recibió.

Y una rotación no termina en el `apply`: termina cuando cada consumidor del
secreto lee el valor nuevo. Con Terraform, eso depende del orden del reemplazo y
de cuándo cada plataforma vuelve a leer el secreto.
