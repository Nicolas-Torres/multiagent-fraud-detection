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

## 5. Rol de acceso — resuelto (el diagnóstico inicial estaba mal)

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

**Bloqueado durante gran parte de la Fase 3**: fallaba con
`MissingSubscription`, y el mismo error aparecía incluso en una simple
*lectura* (`az role assignment list --assignee ...`), a nivel de
resource group y de suscripción entera. El diagnóstico de en ese
momento —demora de propagación del subsistema de RBAC
(`Microsoft.Authorization`) en una suscripción Pay-As-You-Go recién
activada— **resultó incorrecto**, aunque parecía razonable con la
evidencia de ese momento.

### Diagnóstico real

Se resolvió por el Portal (Resource Group → *Access control (IAM)* →
*Add role assignment*, buscando la identidad por nombre) sin ningún
problema — lo cual ya era una pista de que no era un tema de
propagación a nivel de suscripción. La confirmación llegó al aislar la
variable correcta:

```bash
# Con --assignee: sigue fallando incluso con una sesión de az login recién refrescada
az role assignment list --assignee 47529fc8-... --scope ".../rg-fraud-detection"
# ERROR: (MissingSubscription) ...

# Sin --assignee, mismo scope: funciona y muestra la asignación real
az role assignment list --resource-group rg-fraud-detection -o table
# Principal: 47529fc8-...  Role: Contributor  Scope: .../rg-fraud-detection
```

El problema nunca fue el subsistema de RBAC ni la suscripción — fue
específicamente el flag `--assignee` de `az role assignment
list`/`create`, que internamente resuelve la identidad contra
Microsoft Graph antes de operar. Esa resolución puntual fallaba en
esta sesión del CLI (probablemente algo de la cuenta/consentimiento de
Graph para Azure CLI en este tenant), mientras que el Portal resuelve
identidades por otro camino y por eso siempre funcionó. Un `az logout`
+ `az login` fresco tampoco lo arregló — confirma que no era un token
viejo, era el propio comando.

**Lección**: cuando un comando con varios flags falla con un error
genérico, aislar variable por variable (acá: sacar `--assignee` y
listar todo el scope) encuentra la causa real más rápido que asumir la
explicación más "razonable" a primera vista.

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

## 8. Primer bug real en producción — vitrina con `case_id` inexistentes

Al visitar la URL pública, la consola del navegador mostraba varios
`GET /api/v1/cases/{id} 404` en la pestaña Transacción.

### Diagnóstico

El panel de vitrina que carga por defecto usa `CASO_INICIAL` en
`dashboard/src/routes/Transactions.tsx:53`, que sale de
`dashboard/src/data/showcase_cases.json` — un archivo **horneado en el
build del frontend**, no leído en runtime. Ese JSON lo escribe
`scripts/seed_showcase.py`, corriendo el grafo real contra 5
transacciones curadas y guardando los `case_id` resultantes. La imagen
`sha-b642e85` (la que Fase 3 desplegó) tenía ese JSON generado contra
Postgres **local**, nunca contra Neon — los IDs no existían en
producción.

`caj-fraud-detection-seed` (`scripts/seed.py`) no alcanza para esto: el
propio script documenta que sólo carga historial (transacciones,
perfiles, catálogo de políticas, índice vectorial) y **deliberadamente
no crea casos** — crear un caso es correr el pipeline, y eso lo hace
`POST /cases` o un script aparte.

### Corrección, paso a paso

**1. Job base en Azure** (`scripts/seed.py`, sin costo de LLM salvo el
índice):

```bash
az containerapp job start --name caj-fraud-detection-seed --resource-group rg-fraud-detection
```

Primer intento: `Failed`. El log (`az containerapp job logs show
--name caj-fraud-detection-seed ... --tail 100`, requiere `az extension
add --name containerapp --upgrade --yes` primero) mostró que los datos
tabulares cargaron bien (1000 perfiles, 7000 transacciones, 11
políticas) pero la indexación vectorial murió con `429
RESOURCE_EXHAUSTED` de la API de embeddings de Gemini
(`gemini-embedding-2`). Verificado en Google Cloud Console
(`console.cloud.google.com` → API del proyecto → Generative Language
API → Quotas): la cuota diaria daba `unlimited` con `current usage: 8`
— no era un tope agotado, sino un límite de ráfaga (RPM) momentáneo por
indexar muchos chunks seguidos. `seed.py` es idempotente (upsert), así
que un reintento no duplica nada:

```bash
az containerapp job start --name caj-fraud-detection-seed --resource-group rg-fraud-detection
# reintento, unos minutos después: Succeeded
```

**2. `seed_showcase.py` contra Neon, corrido en local** (gasta llamadas
reales a Anthropic y Gemini — 5 corridas del grafo completo):

```bash
DATABASE_URL="<connection string de Neon>" uv run python scripts/seed_showcase.py
# escribe dashboard/src/data/showcase_cases.json con 5 case_id nuevos
```

**3. Commit + PR + merge** del JSON regenerado — rama aparte
(`fix/showcase-cases-azure`), no la de Terraform: es un cambio de datos
del dashboard, no de infraestructura. Verificado por API que el PR #23
quedó `merged`, no sólo cerrado.

**4. Rebuild + push + redeploy manual** (Fase 4 real, el workflow de CD
automático, todavía no existe):

```bash
git checkout main && git pull   # trae el merge, main queda en 231fd93
docker login ghcr.io -u Nicolas-Torres --password-stdin   # PAT temporal, write:packages
docker build -t ghcr.io/nicolas-torres/multiagent-fraud-detection:sha-231fd93 .
docker push ghcr.io/nicolas-torres/multiagent-fraud-detection:sha-231fd93
docker logout ghcr.io
az containerapp update --name ca-fraud-detection-api --resource-group rg-fraud-detection \
  --image ghcr.io/nicolas-torres/multiagent-fraud-detection:sha-231fd93
```

El tag `sha-231fd93` se calculó **después** del merge, no del commit en
la rama — el repo usa *squash merge* (CLAUDE.md), así que el hash del
commit en la rama (`d2b85dd`) no es el que terminó existiendo en
`main`. Usar el hash de la rama habría producido un tag que, según
ADR-0008 (`sha-<7>` = commit real en `main`), apunta a un commit que
nunca estuvo ahí.

El PAT usado para el `docker push` (scope `write:packages`) es
**temporal y distinto** del que vive como secret en la Container App
(`ghcr_token`, scope `read:packages` únicamente, ADR de mínimo
privilegio) — se generó sólo para este push manual y se revoca después
de usarlo, no queda guardado en ningún lado.

`az containerapp update` quedó bloqueado por el clasificador de modo
automático de Claude Code (acción de producción) — lo corrió el
usuario directamente.

### Verificación

```bash
curl .../api/v1/cases/a0cfbbae-...   # 200 — el nuevo case_id de vitrina
curl .../api/v1/cases/c9065a38-...   # 404 — el id viejo, correctamente ya no existe en el frontend desplegado
```

**Lección para Fase 4**: el workflow de CD automático va a necesitar
resolver este mismo problema de origen (el JSON de vitrina depende de
qué base recibió el seed) — probablemente corriendo
`seed_showcase.py` como paso del propio pipeline de build, no a mano,
para que la imagen publicada siempre traiga IDs que existen en la base
a la que apunta.

## 9. Segundo incidente — `internal_policy_rag` degradado en una corrida real

Ejecutando T-3349 desde la web pública, el nodo `internal_policy_rag`
terminó con "Evidencia incompleta... no completó su análisis" — el
mensaje de `@degrades` (regla del proyecto en `CLAUDE.md`), no un
crash del grafo.

### Diagnóstico

Los logs de la Container App (no del Job — la app misma) confirmaron
la causa exacta:

```bash
az extension add --name log-analytics --upgrade --yes
WORKSPACE_ID=$(az monitor log-analytics workspace show \
  --resource-group rg-fraud-detection --workspace-name log-fraud-detection \
  --query customerId -o tsv)
az monitor log-analytics query --workspace "$WORKSPACE_ID" \
  --analytics-query "ContainerAppConsoleLogs_CL | where ContainerAppName_s == 'ca-fraud-detection-api' | where Log_s has 'Traceback' | order by TimeGenerated desc | take 50 | project TimeGenerated, Log_s"
```

```
File "/app/src/multiagent_fraud_detection/graph/nodes.py", line 381, in internal_policy_rag
google.genai.errors.ClientError: 429 RESOURCE_EXHAUSTED
```

Se verificó primero que el índice vectorial estuviera completo en Neon
(no era eso):

```bash
DATABASE_URL="<neon>" uv run python -c "... SELECT count(*) FROM policy_chunks ..."
# policy_chunks: 11, sin embedding: 0 — el índice está completo
```

Y se descartó cuota agotada mirando el panel real de Google Cloud
Console (Generative Language API → Quotas, filtrado por
`gemini-embedding-2`): RPM 3000 (uso: 12), TPM 1M (uso: 368), RPD
ilimitado (uso: 29) — muy lejos de cualquier tope. `nodes.py` sólo
llama al embedder en un único punto (línea 340, dentro de
`internal_policy_rag`, una vez por caso) — no hay ráfaga propia de
llamadas concurrentes que lo explique tampoco.

**Conclusión**: un límite de ráfaga por segundo, no documentado en el
panel de cuota agregada, contra el que el retry interno del SDK
`google-genai` (basado en `tenacity`, fuera de nuestro control) no
alcanzó a protegernos en este caso puntual. `@degrades` hizo exactamente
lo que tiene que hacer — degradar con un mensaje honesto en vez de
inventar una señal — así que esto no bloquea nada, queda como mejora
pendiente: envolver la llamada de `embeddings.py`/`nodes.py:340` con un
retry propio (backoff de varios segundos, no el de milisegundos del
SDK) para absorber esta clase de ráfaga transitoria antes de llegar a
degradar. No implementado todavía — el usuario prefirió anotarlo y
seguir.

---

## 10. Fase 4 — workflow de CD (`deploy-azure.yml`)

`.github/workflows/deploy-azure.yml`, disparado por `workflow_run`
cuando `CI` termina bien contra `main` (nunca reconstruye la imagen —
usa el mismo `sha-<7>` que el job `build` de `ci.yml` ya publicó,
calculado de `github.event.workflow_run.head_sha`).

Orden de los pasos, seguido a ADR-0009/0010:

1. `az containerapp job update --image` + `job start` sobre
   `caj-fraud-detection-migrate`, sondeado hasta que termine. Si no
   sale `Succeeded`, el step falla (`exit 1`) y el workflow se corta
   ahí — la Container App **no** se toca, sigue sirviendo la imagen
   anterior.
2. Sólo si migrar salió bien: `az containerapp update --image` sobre
   `ca-fraud-detection-api` — este es el momento real de "ir a
   producción".
3. `caj-fraud-detection-seed`, actualizado y disparado con
   `continue-on-error: true` — no bloqueante, igual que en local.
4. `caj-fraud-detection-fetch-intel`, sólo actualizado (no disparado —
   corre solo, por su propio cron).

Login vía `azure/login@v2` con OIDC (`id-token: write` en
`permissions:`) contra la misma identidad `github-oidc-fraud-detection`
de §4 — sin ningún secreto estático.

**Actualización**: el role assignment de §5 ya está confirmado — la
identidad `github-oidc-fraud-detection` tiene `Contributor` real sobre
`rg-fraud-detection`. El archivo está escrito y validado
sintácticamente (`yaml.safe_load`); la primera corrida real sólo
queda pendiente de cargar los secrets (siguiente punto).

**Pendiente antes de la primera corrida real**: cargar los tres
secrets del repo (`AZURE_CLIENT_ID`, `AZURE_TENANT_ID`,
`AZURE_SUBSCRIPTION_ID`) en GitHub — Settings → Secrets and variables →
Actions. Cargados vía API (`PUT /repos/.../actions/secrets/{name}`,
cifrados con la public key del repo usando `pynacl.SealedBox` — el
mismo cifrado que usa `gh secret set` por debajo, sin tener `gh`
instalado).

### Primera corrida real — 2026-09-07

Merge de PR #25 a `main` (commit `94d91d0`) disparó `CI` normalmente,
que terminó en `success`, que a su vez disparó `Deploy a Azure` por
`workflow_run` — sin ningún paso manual.

```bash
curl "https://api.github.com/repos/.../actions/runs?head_sha=94d91d0..."
# CI: completed / success
# Deploy a Azure: in_progress -> (poco después) completed / success
```

Verificado que la Container App terminó sirviendo exactamente esa
imagen, no una vieja:

```bash
az containerapp show --name ca-fraud-detection-api --resource-group rg-fraud-detection \
  --query "properties.template.containers[0].image" -o tsv
# ghcr.io/nicolas-torres/multiagent-fraud-detection:sha-94d91d0

curl .../health   # 200
curl .../ready    # 200
```

**Fase 4 cerrada**: push a `main` → CI → build/push a GHCR → migrar
(con abort-on-failure) → actualizar la Container App, de punta a
punta, sin intervención manual, primera vez.

<!-- Sigue con: 1) resolver la lección de §8 (seed_showcase.py como
parte del pipeline de build, no manual — el próximo deploy real va a
volver a romper la vitrina si no se resuelve antes), 2) Fase 5 —
verificación end-to-end + cierre de README/acta. -->
