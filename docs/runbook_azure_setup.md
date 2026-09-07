# Bitácora — poner en marcha Azure Container Apps (Fase 3, ADR-0021)

> Registro paso a paso de cómo se armó la infraestructura real en Azure,
> con el comando exacto, qué produjo, y por qué se hizo así. No es sólo
> para reproducirlo — es para que quede claro qué existe y cómo se
> configuró, sin tener que releer todo el chat.
>
> Convención igual que `docs/runbook_base_nueva.md`: cada paso termina con
> algo verificable, no con "no dio error".

---

## 0. Contexto de arranque

Suscripción de Azure: **no existía** al empezar esta fase — `az login`
devolvía `No subscriptions found`. El usuario activó **Pay-As-You-Go**
durante esta misma sesión.

```
Suscripción: Suscripción 1
id:          6bf9c7de-db5d-4857-8851-e5c1830d3833
tenant:      e4fed520-feb2-4afd-b3f4-ab4677eeb46d ("Directorio predeterminado")
región:      eastus2
```

`az login` requiere completar el flujo con MFA en un navegador — no es
automatizable, lo hace el usuario. El comando `--use-device-code` es más
confiable que el login interactivo normal cuando no hay certeza de que el
navegador se abra solo desde la terminal.

---

## 1. Registrar los resource providers

Una suscripción nueva no trae registrados los providers de los recursos
que todavía nunca usó — hay que registrarlos antes de poder crearlos.

```bash
az provider register -n Microsoft.App                  # Container Apps
az provider register -n Microsoft.Storage               # Storage Account (backend de Terraform)
az provider register -n Microsoft.OperationalInsights    # Log Analytics (lo exige Container Apps Environment)
```

Es asíncrono — hay que sondear hasta que las tres digan `Registered`:

```bash
az provider show -n Microsoft.App --query registrationState -o tsv
```

**Verificación**: las tres en `Registered` (tardó ~50s en esta corrida).

---

## 2. Resource group

Un solo resource group para todo el proyecto — no hay razón para
separarlo en varios en esta escala.

```bash
az group create --name rg-fraud-detection --location eastus2
```

**Verificación**: `provisioningState: Succeeded` en la respuesta.

---

## 3. Storage Account + contenedor — backend remoto de Terraform

Por qué a mano y no con Terraform: el backend remoto tiene que *existir*
antes de que haya un Terraform que lo use — es la única pieza de
infraestructura que no gestiona el propio Terraform (ADR-0021).

Antes de crearlo, se confirmó que el nombre está libre (los nombres de
Storage Account son globales, no sólo únicos dentro de la suscripción):

```bash
az storage account check-name --name stfrauddetecttf
# nameAvailable: true
```

```bash
az storage account create \
  --name stfrauddetecttf \
  --resource-group rg-fraud-detection \
  --location eastus2 \
  --sku Standard_LRS \
  --kind StorageV2 \
  --min-tls-version TLS1_2 \
  --allow-blob-public-access false
```

`Standard_LRS` (redundancia local, la más barata) alcanza de sobra para
un archivo de estado de Terraform — no es un dato que necesite
redundancia geográfica. `allow-blob-public-access false` porque el
estado de Terraform puede contener valores sensibles (aunque acá no
metamos secretos reales adentro, es la postura por defecto correcta).

```bash
az storage container create \
  --name tfstate \
  --account-name stfrauddetecttf \
  --auth-mode login
```

`--auth-mode login` usa la identidad de Azure AD ya logueada (la del
usuario) en vez de la clave de la cuenta — evita manejar y guardar esa
clave sólo para crear un contenedor.

**Verificación**: `{"created": true}`.

---

## 4. App Registration + Service Principal — identidad de GitHub Actions

GitHub Actions necesita autenticarse contra Azure para que el CD pueda
crear/actualizar recursos. La decisión (ADR-0021) es **OIDC, no un
secreto estático**: un token de vida cortísima por corrida, nunca una
clave guardada en GitHub que no expira.

```bash
az ad app create --display-name "github-oidc-fraud-detection"
# appId: 47529fc8-16d8-4fb4-9775-40b01e385682
# id (object id): 423c2f89-17cf-495a-bcbd-3723cf2f9384
```

Una **App Registration** por sí sola no es una identidad que se pueda
usar — hace falta el **Service Principal** asociado, que es lo que
realmente recibe permisos:

```bash
az ad sp create --id 47529fc8-16d8-4fb4-9775-40b01e385682
```

### Federated credential — el corazón de OIDC

Esto es lo que le dice a Azure AD "confiá en un token que emita GitHub
Actions para *este* repo, en *esta* rama, sin que yo tenga que guardar
ninguna clave":

```json
{
  "name": "github-main-branch",
  "issuer": "https://token.actions.githubusercontent.com",
  "subject": "repo:Nicolas-Torres/multiagent-fraud-detection:ref:refs/heads/main",
  "audiences": ["api://AzureADTokenExchange"]
}
```

```bash
az ad app federated-credential create \
  --id 423c2f89-17cf-495a-bcbd-3723cf2f9384 \
  --parameters federated-cred.json
```

El `subject` es la parte que importa: acota la confianza a corridas de
GitHub Actions que sean *exactamente* un push a `main` de *este* repo —
un PR, una rama distinta, o un fork no van a poder pedir un token válido
con esta credencial. Si más adelante el CD también necesita correr sobre
tags de versión (`vX.Y.Z`), hace falta una *segunda* federated credential
con un `subject` distinto (`ref:refs/tags/*` no es válido tal cual, GitHub
exige el patrón exacto por tag o por rama — se resuelve cuando llegue esa
necesidad, no antes).

**Verificación**: la respuesta trae el `id` de la credential creada.

---

## 5. Rol de acceso — bloqueado, propagación de RBAC

Plan: `Contributor`, pero **acotado sólo al resource group**
`rg-fraud-detection` (no a nivel de toda la suscripción) — mínimo
privilegio: si esta identidad se compromete, el daño queda contenido a
los recursos de este proyecto.

```bash
az role assignment create \
  --assignee 47529fc8-16d8-4fb4-9775-40b01e385682 \
  --role "Contributor" \
  --scope "/subscriptions/6bf9c7de-db5d-4857-8851-e5c1903d3833/resourceGroups/rg-fraud-detection"
```

**Bloqueado por ahora**: falla con `MissingSubscription`, y el mismo
error aparece incluso en una simple *lectura* de asignaciones de rol
(`az role assignment list`), a nivel de resource group **y** de
suscripción entera. Se descartó que sea un problema del comando puntual
— es el subsistema de RBAC (`Microsoft.Authorization`) de una suscripción
Pay-As-You-Go recién activada, que en la práctica tarda en inicializarse
más que el resto de los providers (Storage y Resources ya respondían
bien al momento de este bloqueo). No es algo que un reintento inmediato
resuelva — se retoma más adelante en esta misma bitácora, en la sección
correspondiente, una vez que se destrabe solo.

---

## 6. Módulo Terraform (`infra/azure/`)

Con el bootstrap manual (§1-4) hecho y el backend remoto ya existiendo,
el resto de la infraestructura sí se gestiona con Terraform. Cinco
archivos:

### `backend.tf`

Apunta al Storage Account/contenedor creados a mano en §3. No lleva
credenciales adentro — Terraform usa la sesión de `az login` (o, en CI,
el login OIDC) para autenticarse contra el blob.

### `providers.tf`

`required_version >= 1.9`, provider `azurerm ~> 4.0`. Sin configuración
extra en el bloque `provider "azurerm" {}` — no hace falta, ya toma la
suscripción activa de `az account show`.

### `variables.tf`

Todo lo que puede cambiar sin tocar el `.tf` — nombre del RG, región,
imagen (Fase 4 la va a sobreescribir en cada deploy), credenciales de
GHCR, y los cuatro secretos de runtime (`DATABASE_URL`,
`ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `LANGSMITH_API_KEY`). Los
sensibles llevan `sensitive = true` — Terraform los oculta en la salida
de `plan`/`apply`, aunque igual quedan en texto plano dentro del state
remoto (de ahí que el Storage Account tenga `allow-blob-public-access
false`, §3).

`ghcr_username`, `database_url`, `anthropic_api_key` y `gemini_api_key`
no tienen `default` — Terraform los va a pedir interactivamente o hay
que pasarlos con `-var`/`TF_VAR_*`. Nunca en el `.tf` ni commiteados.

### `main.tf`

- `data "azurerm_resource_group" "main"` — lee el RG de §2, no lo crea.
- `azurerm_log_analytics_workspace` — Container Apps Environment lo
  exige para logs/métricas; `PerGB2018` es el sku de consumo, sin
  compromiso fijo.
- `azurerm_container_app_environment` — el "clúster lógico" que agrupa
  la Container App y los tres Jobs.
- Un bloque `locals` con los 5 secrets y las variables de entorno,
  armado una sola vez y reusado en los 4 recursos de cómputo vía
  `dynamic "secret"`/`dynamic "env"` — evita repetir el mismo bloque
  cuatro veces con el riesgo de que se desincronicen.
- `azurerm_container_app.api` — el modo *servir*: `min_replicas = 1` y
  `max_replicas = 1` (ADR-0021: costo fijo a propósito, nunca en cero),
  `ingress` externo en el puerto 8000, `liveness_probe`/
  `readiness_probe` contra `/health` y `/ready`. La imagen inicial es
  `var.image` (la última publicada en Fase 2) — a partir del primer
  deploy real, Fase 4 la actualiza con `az containerapp update --image`
  sin volver a correr `apply`.
- Tres `azurerm_container_app_job`:
  - `migrate`: `trigger_type` Manual, `replica_retry_limit = 0` (ADR-0009:
    nunca reintentar una migración fallida sola).
  - `seed`: Manual, `replica_retry_limit = 1` (ADR-0010: idempotente, un
    reintento no rompe nada).
  - `fetch-intel`: Schedule, `cron_expression = var.fetch_intel_cron`
    (`0 6 * * *` UTC de arranque).

### `outputs.tf`

`api_fqdn` (URL pública completa, con `https://`), más el nombre del RG
y el id del Environment por si otro módulo los necesita después.

### Verificación de sintaxis (sin tocar la nube)

```bash
cd infra/azure
terraform fmt -diff      # corrigió alineación de = en backend.tf y main.tf
terraform init -backend=false   # sólo descarga el provider, no toca el backend remoto
terraform validate
```

**Resultado**: `Success! The configuration is valid.` — confirma que el
HCL es sintácticamente correcto y que los tipos de recurso/argumentos
existen en el provider `azurerm` 4.81.0, pero **no** confirma que vaya a
aplicar bien contra la suscripción real (eso lo valida recién
`terraform plan`, con el backend real conectado).

Pendiente antes de `plan`/`apply`: que se destrabe el role assignment
de §5, y decidir/crear el proyecto de Neon para tener un `DATABASE_URL`
real que pasarle a `-var`.

### `terraform plan` de prueba, contra la API real de Azure

Con el backend ya conectado (`terraform init` completo, sin
`-backend=false`), se corrió un `plan` real con valores *placeholder*
en los cinco secretos (no son secretos válidos — es sólo para que
Terraform no se detenga a pedirlos, ya que en el plan no se validan
contra ningún servicio):

```bash
terraform plan \
  -var="ghcr_username=nicolas-torres" \
  -var="ghcr_token=placeholder-pat-read-packages" \
  -var="database_url=postgresql://placeholder" \
  -var="anthropic_api_key=placeholder" \
  -var="gemini_api_key=placeholder"
```

**Resultado**: `Plan: 6 to add, 0 to change, 0 to destroy` — exactamente
los 6 recursos del módulo (workspace, environment, la Container App y
los 3 Jobs). Esto confirma dos cosas a la vez:

1. La lectura del resource group real (`data.azurerm_resource_group`)
   funcionó — es una llamada de verdad a la API de Azure, no sólo
   validación local.
2. **El bloqueo de RBAC de §5 no afecta esto.** Ese bloqueo es sobre el
   *Service Principal* de GitHub Actions (`github-oidc-fraud-detection`)
   pidiendo su propio rol — una operación de `Microsoft.Authorization`.
   `terraform plan`/`apply` corridos a mano usan la sesión de `az login`
   del usuario (que ya es dueño de la suscripción), y crear/leer
   recursos de Storage, Container Apps o Log Analytics no pasa por
   `Microsoft.Authorization` en absoluto. En otras palabras: el `apply`
   real ya se podría hacer hoy sin esperar a que el rol se destrabe —
   lo que sí depende de ese rol es el futuro workflow de CD (Fase 4),
   que corre como el Service Principal, no como el usuario.

Lo que sigue faltando para un `apply` real (no de prueba) es tener
valores *genuinos* en esas cinco variables: un PAT de GitHub con
`read:packages`, y un proyecto de Neon con su connection string.

## 7. `terraform apply` real — infraestructura ya arriba

Con Neon (free tier, región `us-east-2`, extensión `vector` habilitada a
mano vía `CREATE EXTENSION IF NOT EXISTS vector;` en su SQL Editor) y un
PAT de GitHub (`read:packages`, acotado sólo a este repo) ya generados,
se corrió el `apply` real.

### Bug encontrado en el primer intento

El primer `apply` creó 2 de los 6 recursos (`azurerm_log_analytics_workspace`,
`azurerm_container_app_environment`) y falló en los otros 4 con:

```
ContainerAppSecretInvalid: Invalid Request: Container app secret(s)
with name(s) 'langsmith-api-key' are invalid: value or keyVaultUrl
and identity should be provided.
```

Causa: `var.langsmith_api_key` tiene `default = ""` (es opcional, por
diseño — ADR-0013: sin clave, el sistema funciona igual sin trazar),
pero Azure Container Apps **rechaza declarar un secret con valor
vacío** — exige un valor real o una referencia a Key Vault. El primer
`-var-file` armado en esta sesión, además, se olvidó de copiar
`LANGSMITH_API_KEY` desde el `.env` local (sólo copiaba Anthropic y
Gemini), así que cayó en ese default vacío sin necesidad.

Dos arreglos, no uno solo:

1. **El olvido puntual**: agregar la clave real al archivo de variables.
2. **El bug de fondo en el `.tf`**, que iba a repetirse con cualquier
   entorno que no configure LangSmith (el caso legítimo que el propio
   diseño del sistema contempla): en `main.tf`, `local.container_secrets`
   y `local.container_env` ahora arman el par `langsmith-api-key` con
   `concat(...)` y una lista vacía cuando `var.langsmith_api_key == ""`
   — el secret ni se declara si no hay una clave real, en vez de
   declararlo vacío y que Azure lo rechace.

Reintentado con el fix: `terraform plan` mostró `4 to add` (los 2 ya
creados no se tocan — Terraform es idempotente respecto al state real),
y el `apply` los creó sin errores.

### Resultado

```
Apply complete! Resources: 4 added, 0 changed, 0 destroyed.

Outputs:
api_fqdn = "https://ca-fraud-detection-api.graywave-cc1ab2d2.eastus2.azurecontainerapps.io"
```

```bash
curl https://ca-fraud-detection-api.graywave-cc1ab2d2.eastus2.azurecontainerapps.io/health   # 200
curl https://ca-fraud-detection-api.graywave-cc1ab2d2.eastus2.azurecontainerapps.io/ready    # 200 (¡ya!)
```

`/ready` dio 200 antes incluso de migrar — porque sólo hace `SELECT 1`
(`src/multiagent_fraud_detection/api/app.py`): confirma que la
Container App llega a Neon, no que el esquema exista. Se corrió la
migración real igual, como preveía el plan:

```bash
az containerapp job start --name caj-fraud-detection-migrate --resource-group rg-fraud-detection
# execution: caj-fraud-detection-migrate-z51xfkd
az containerapp job execution show --name caj-fraud-detection-migrate \
  --resource-group rg-fraud-detection \
  --job-execution-name caj-fraud-detection-migrate-z51xfkd \
  --query properties.status -o tsv
# Succeeded
```

**Estado actual**: infraestructura real arriba y con esquema migrado.
Pendiente, sin bloquear lo anterior: el role assignment de §5 (necesario
recién para Fase 4/CD automático), y decidir si sembrar datos de vitrina
(`caj-fraud-detection-seed`) ahora o dejarlo para cuando exista el
workflow de deploy.

Nota de costo: el usuario decidió sostener esto ~1 mes a este nivel de
gasto («una decena de dólares») para evaluar el portafolio en vivo, y
después revisar una opción más barata si conviene — no es una decisión
cerrada para siempre.

<!-- Sigue con Fase 4: el workflow de CD (build → push a GHCR → az
containerapp update --image → correr el Job de migrar antes, abortando
el deploy si falla, por ADR-0009). -->
