# infra/azure — bootstrap manual

Detalle completo, comando por comando y con el porqué de cada uno, en
`docs/runbook_azure_setup.md`. Esto es sólo el resumen ejecutable para
reproducir el entorno sin releer toda la bitácora.

## 0. Una sola vez, fuera de Terraform (ADR-0021)

El backend remoto y la identidad de GitHub Actions no pueden nacer
_dentro_ de este módulo: el primero porque Terraform necesita que el
backend ya exista antes de poder usarlo; la segunda porque es la
credencial con la que correría el propio Terraform en CI.

```bash
# 1. Providers
az provider register -n Microsoft.App
az provider register -n Microsoft.Storage
az provider register -n Microsoft.OperationalInsights

# 2. Resource group
az group create --name rg-fraud-detection --location eastus2

# 3. Backend remoto (Storage Account + contenedor blob)
az storage account create --name stfrauddetecttf --resource-group rg-fraud-detection \
  --location eastus2 --sku Standard_LRS --kind StorageV2 \
  --min-tls-version TLS1_2 --allow-blob-public-access false
az storage container create --name tfstate --account-name stfrauddetecttf --auth-mode login

# 4. Identidad OIDC para GitHub Actions
az ad app create --display-name "github-oidc-fraud-detection"
az ad sp create --id <appId>
az ad app federated-credential create --id <objectId> --parameters federated-cred.json

# 5. Rol, acotado al resource group (mínimo privilegio)
az role assignment create --assignee <appId> --role "Contributor" \
  --scope "/subscriptions/<sub>/resourceGroups/rg-fraud-detection"
```

## 1. Terraform

```bash
cd infra/azure
terraform init
terraform plan \
  -var="ghcr_username=<usuario de GitHub>" \
  -var="ghcr_token=<PAT con read:packages>" \
  -var="database_url=<connection string de Neon>" \
  -var="anthropic_api_key=<...>" \
  -var="gemini_api_key=<...>"
# revisar el plan completo antes de:
terraform apply <mismas -var>
```

Ninguna de las variables sensibles tiene default — Terraform las pide
si no se pasan. No van en un `.tfvars` commiteado.

## 2. Después del primer `apply`

`/ready` va a fallar hasta correr la migración una vez (todavía no hay
CD automático — eso es Fase 4):

```bash
az containerapp job start --name caj-fraud-detection-migrate --resource-group rg-fraud-detection
curl https://<api_fqdn>/health
curl https://<api_fqdn>/ready
```
