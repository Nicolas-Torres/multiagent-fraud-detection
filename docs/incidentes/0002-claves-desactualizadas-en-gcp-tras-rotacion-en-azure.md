# Incidente 0002 — claves desactualizadas en GCP tras rotar sólo en Azure

**Fecha**: 2026-09-15, el día siguiente al incidente 0001.
**Detectado**: por el usuario, ejecutando una transacción de prueba en el
despliegue de GCP — nodos en rojo, mensaje "Evidencia incompleta" en el
dashboard. No hubo alerta del sistema.

> Este doc se escribe en retrospectiva, junto con el incidente 0003, para
> resolver una referencia que [ADR-0023](../adr/0023-un-solo-archivo-de-secretos-compartido-entre-azure-y-gcp.md)
> ya citaba como "incidente 0002" sin que existiera el archivo.

## Síntoma

Corriendo una transacción contra el despliegue de GCP, varios nodos del
grafo quedaron degradados en la misma corrida:
`internal_policy_rag`, `debate_pro_fraud`, `debate_pro_customer`,
`decision_arbiter`, `explainability` — el patrón exacto de "el proveedor no
responde" en cascada, no un fallo aislado de un nodo.

## Causa raíz

Como parte del cierre del incidente 0001, se rotaron `anthropic_api_key` y
`gemini_api_key` — pero sólo en `infra/azure/terraform.tfvars`. GCP tiene su
propio Secret Manager con su propia copia de esos valores
(`infra/gcp/main.tf`), independiente del de Azure pese a ser, en teoría, el
mismo secreto lógico. Rotar en un lado no propaga al otro: GCP siguió
sirviendo con las claves viejas, ya revocadas del lado del proveedor.

Es el mismo mecanismo que ya había pasado antes en la sesión con
`database-url` (rotada en Azure, GCP se quedó sirviendo con la contraseña
vieja de Neon) — dos veces el mismo olvido, no mala suerte.

## Fix inmediato

`gcloud secrets versions add anthropic-api-key`/`gemini-api-key` con un
archivo local temporal (confirmado fuera de control de versiones, borrado
después de usarlo) para poner al día las copias de GCP con los valores
reales ya vigentes en Anthropic/Google AI Studio.

## Fix sistémico

[ADR-0023](../adr/0023-un-solo-archivo-de-secretos-compartido-entre-azure-y-gcp.md):
un solo `infra/shared.secrets.tfvars` y `infra/rotate-secrets.sh plan|apply`
que corre Terraform en las dos carpetas con el mismo archivo en una sola
invocación — rotar deja de ser dos pasos manuales que hay que recordar y
pasa a ser uno.

## Pendiente

- No hubo alerta del sistema — se detectó por el mensaje de confianza
  degradada en el dashboard, igual que el incidente 0001 se detectó por
  saldo agotado. Sigue sin existir alertado activo para ninguno de los dos
  casos; queda como mejora aparte, no abordada acá.
