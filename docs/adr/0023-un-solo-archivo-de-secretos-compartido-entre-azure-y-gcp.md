# ADR-0023: un solo archivo de secretos compartido entre Azure y GCP

- **Estado**: aceptado
- **Fecha**: 2026-09-15

## Contexto

`infra/azure` e `infra/gcp` declaran, cada uno, las mismas cinco
variables sensibles (`ghcr_token`, `database_url`, `anthropic_api_key`,
`gemini_api_key`, `langsmith_api_key`) apuntando al mismo valor real
—ADR-0022 ya lo dice explícitamente para `database_url`: "los cinco
secrets de runtime son los mismos valores que ya usa Azure"—. Hasta
ahora cada uno se cargaba por separado, con `-var`/un `terraform.tfvars`
propio por nube.

Eso ya causó dos incidentes reales, seguidos, con el mismo mecanismo:
rotar un secreto en una nube y olvidar la otra. `docs/incidentes/0001`
documenta la fuga de crédito de fetch-intel; al día siguiente, rotar
`anthropic_api_key`/`gemini_api_key` sólo en Azure dejó GCP sirviendo
con las claves viejas ya revocadas —cinco nodos del grafo
(`internal_policy_rag`, `debate_pro_customer`, `debate_pro_fraud`,
`decision_arbiter`, `explainability`) degradados en cada transacción
evaluada ahí hasta que se detectó por el mensaje de confianza degradada
en el dashboard, no por ninguna alerta—. Dos veces el mismo olvido no es
mala suerte, es que el proceso tiene un paso manual duplicado que
depende de acordarse.

## Decisión

**Un solo archivo, `infra/shared.secrets.tfvars`** (gitignored,
documentado sin valores en `infra/shared.secrets.tfvars.example`) con
las cinco variables que Azure y GCP declaran idénticas por nombre. Un
wrapper, `infra/rotate-secrets.sh plan|apply`, corre `terraform
plan`/`apply` en las dos carpetas con ese mismo archivo en una sola
invocación — rotar deja de ser "dos operaciones que hay que acordarse
de hacer" y pasa a ser una.

El wrapper detecta la imagen que ya está corriendo en cada nube
(`az containerapp show` / `gcloud run services describe`) y la pasa
como `-var` en vez de dejar que Terraform caiga al `default` de cada
`variables.tf` — ese default queda desactualizado en cada deploy de CD
(que actualiza la imagen fuera de `apply`, ADR-0009/0010), y sin este
paso cada `plan` de rotación traería de arrastre un cambio de imagen no
pedido — exactamente lo que pasó a mano el 2026-09-14 antes de
descubrir esta causa.

`ghcr_username`, aunque no es secreto, entra al mismo archivo: es el
mismo valor real en las dos nubes y su ausencia ya causó un diff
espurio (`Nicolas-Torres` vs. el placeholder `nicolas-torres` del
runbook) el mismo día del incidente 0001.

`infra/azure/terraform.tfvars.example` (creado durante el incidente
0001) se mantiene aparte: sigue sirviendo para un `apply` manual de
*infraestructura* de una sola nube (como el `replica_retry_limit` de
ese mismo incidente), que sí necesita `image`/vars propias de esa
carpeta y no encaja en "rotar un secreto compartido".

## Alternativas descartadas

**Gestor de secretos centralizado (Vault, Doppler, Infisical, 1Password
Secrets Automation).** Es la respuesta correcta para un sistema
multi-nube real, con rotación automática y sincronización activa hacia
cada proveedor. Para un portafolio de dos despliegues (uno de
aprendizaje) es una herramienta y una cuenta más para mantener a cambio
de resolver un problema que un archivo compartido ya resuelve.

**Secretos dinámicos de corta vida** (ej. Vault emitiendo credenciales
de Postgres al vuelo, sin contraseña estática que rotar). Tiene sentido
real para `database_url`; no aplica a `anthropic_api_key`/
`gemini_api_key`, que son estáticas por naturaleza —las emite la
consola del proveedor, no algo que este proyecto pueda automatizar del
todo—.

**Dejar cada `terraform.tfvars` por separado y agregar sólo un
checklist en el runbook** ("al rotar X, actualizá también Y"). Un
checklist manual es exactamente el paso que ya falló dos veces
seguidas; automatizar la propagación elimina la clase de error, no sólo
la documenta.

## Consecuencias

**Se gana**: una sola fuente de verdad para los cinco secretos
compartidos, y un solo comando que los propaga a las dos nubes vía el
camino ya trackeado por Terraform (sin tocar los secret stores nativos
por fuera del estado, que fue el atajo usado para destrabar el
incidente 0002 en el momento pero que puede desincronizar el
`terraform.tfstate` de cada nube si no se corrige acá).

**Se paga**:

- Un archivo más para el checklist de "onboarding en máquina nueva"
  —además de `.env`, ahora también `infra/shared.secrets.tfvars`—.
- El wrapper asume nombres de recursos fijos (`ca-fraud-detection-api`,
  `fraud-detection-api`, `rg-fraud-detection`,
  `fraud-detection-portafolio`) en vez de leerlos de Terraform —
  aceptable porque son fijos en este proyecto, pero es un acoplamiento
  que un script más general no tendría.
- Sigue sin resolver la rotación en sí: cambiar la clave en la consola
  de cada proveedor (Anthropic, Google AI Studio, GitHub, Neon) sigue
  siendo manual — este ADR resuelve la propagación, no la emisión.
