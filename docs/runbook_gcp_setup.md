# Bitácora — poner en marcha GCP Cloud Run (Fase 6, ADR-0022)

> Registro paso a paso, mismo formato y mismo propósito que
> `docs/runbook_azure_setup.md`: comando exacto, qué produjo, y por qué
> — para que quede claro qué existe y cómo se configuró, no sólo que
> funciona.

---

## 0. Contexto de arranque

Cuenta de Google (`nitvnk11@gmail.com`) con proyectos previos de otro
trabajo (`Taller-1` es, de hecho, el mismo proyecto cuya API key de
Gemini usa este sistema para embeddings/LLM — nada que ver con la
infraestructura de despliegue). Login del CLI vencido al empezar
(`invalid_grant`) — se rehace con `gcloud auth login`, corrido por el
usuario en una terminal aparte (el flujo OAuth necesita pegar un código
de vuelta; el `!` de Claude Code no da una terminal interactiva real
para eso).

Dos credenciales distintas, dos logins:
- `gcloud auth login` — la identidad con la que opera el CLI.
- `gcloud auth application-default login` — Application Default
  Credentials, las que usa cualquier librería/herramienta que hable
  directo con las APIs de Google (Terraform, entre otras). Al
  autorizar, el scope correcto es **"ver, modificar, configurar y
  eliminar mis datos de cuenta de Google Cloud..."** (`cloud-platform`)
  — el de Cloud SQL no aplica, la base es Neon, fuera de GCP.

Facturación: una sola cuenta abierta, **"My Billing Account"**
(`0182F2-29C347-7CB6C2`) — la otra está cerrada y el trial de GCP ya
estaba usado (mismo patrón que el trial de Azure en la Fase 3).

---

## 1. Proyecto nuevo y dedicado

Igual que `rg-fraud-detection` en Azure: aislado del resto de
proyectos de la cuenta (`Taller-1`, `Gemini API`, `My First Project`),
para no mezclar costos ni permisos.

```bash
gcloud projects create fraud-detection-portafolio --name="fraud-detection-portafolio"
gcloud config set project fraud-detection-portafolio
gcloud billing projects link fraud-detection-portafolio --billing-account=0182F2-29C347-7CB6C2
```

**Verificación**: `billingEnabled: true` en la respuesta del link.

---

## 2. Habilitar las APIs necesarias

```bash
gcloud services enable \
  run.googleapis.com \
  cloudscheduler.googleapis.com \
  iamcredentials.googleapis.com \
  secretmanager.googleapis.com \
  storage.googleapis.com \
  cloudresourcemanager.googleapis.com \
  --project=fraud-detection-portafolio
```

`iamcredentials.googleapis.com` es la que hace posible la
impersonación (Workload Identity Federation, §4) — sin ella, un
Workload Identity Pool no tiene con qué generar el token de corta vida
que GitHub Actions termina usando.

**Verificación**: `gcloud services list --enabled` muestra las seis.

---

## 3. Bucket de Cloud Storage — backend remoto de Terraform

Mismo motivo que el Storage Account de Azure: tiene que existir antes
de que haya un Terraform que lo use.

```bash
gcloud storage buckets create gs://fraud-detection-portafolio-tfstate \
  --project=fraud-detection-portafolio \
  --location=us-central1 \
  --uniform-bucket-level-access \
  --public-access-prevention
gcloud storage buckets update gs://fraud-detection-portafolio-tfstate --versioning
```

`us-central1` (Iowa) por ser de las regiones más baratas y con
disponibilidad completa de Cloud Run — sin apuro por cambiarla.
`--public-access-prevention` es el equivalente de GCP a
`allow-blob-public-access false` en Azure. Versionado activado sobre
el bucket: si un `apply` corrompe el state, la versión anterior sigue
recuperable — Azure no lo necesitó porque Blob Storage con `--auth-mode
login` ya da un nivel de protección distinto, pero en GCS es la forma
estándar de protegerse contra un state roto.

**Verificación**: `versioning_enabled: true` en el describe.

---

## 4. Workload Identity Federation — identidad de GitHub Actions

Equivalente de GCP a la *federated credential* de Azure AD (ADR-0021/0022):
ningún secreto estático, un token de vida corta por corrida.

```bash
gcloud iam workload-identity-pools create github-actions-pool \
  --project=fraud-detection-portafolio \
  --location=global \
  --display-name="GitHub Actions"

gcloud iam workload-identity-pools providers create-oidc github-actions-provider \
  --project=fraud-detection-portafolio \
  --location=global \
  --workload-identity-pool=github-actions-pool \
  --display-name="GitHub Actions Provider" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref" \
  --attribute-condition="assertion.repository=='Nicolas-Torres/multiagent-fraud-detection' && assertion.ref=='refs/heads/main'" \
  --issuer-uri="https://token.actions.githubusercontent.com"
```

El `--attribute-condition` es el equivalente exacto del `subject`
acotado de la federated credential de Azure: sólo un token OIDC de
GitHub Actions que declare *este* repo, en la rama `main`, pasa —un
PR, una rama distinta o un fork quedan afuera.

```bash
gcloud iam service-accounts create github-actions-deployer \
  --project=fraud-detection-portafolio \
  --display-name="GitHub Actions deployer (WIF)"
```

Un Workload Identity Pool por sí solo no es una identidad usable —hace
falta un Service Account que el pool pueda *impersonar*, que es lo que
realmente ejecuta las acciones:

```bash
PROJECT_NUMBER=$(gcloud projects describe fraud-detection-portafolio --format="value(projectNumber)")
# 432475042270

gcloud iam service-accounts add-iam-policy-binding \
  github-actions-deployer@fraud-detection-portafolio.iam.gserviceaccount.com \
  --project=fraud-detection-portafolio \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github-actions-pool/attribute.repository/Nicolas-Torres/multiagent-fraud-detection"
```

**Verificación**: la respuesta trae el `binding` con el
`principalSet://...` como `member`.

---

## 5. Rol IAM del Service Account

A diferencia de Azure (un solo `Contributor` acotado al resource
group), GCP no tiene un rol "administra todo lo de este proyecto salvo
IAM" tan directo para lo que hace falta acá — se arma con roles
puntuales por servicio, todos a nivel de proyecto (que es, en los
hechos, el equivalente de `rg-fraud-detection`: un proyecto dedicado
únicamente a esto):

```bash
for role in roles/run.admin roles/iam.serviceAccountUser roles/cloudscheduler.admin roles/secretmanager.admin roles/storage.admin; do
  gcloud projects add-iam-policy-binding fraud-detection-portafolio \
    --member="serviceAccount:github-actions-deployer@fraud-detection-portafolio.iam.gserviceaccount.com" \
    --role="$role" \
    --condition=None
done
```

| Rol | Para qué |
|---|---|
| `roles/run.admin` | Crear/actualizar el Cloud Run service y los tres Jobs |
| `roles/iam.serviceAccountUser` | "Actuar como" el Service Account de runtime que cada recurso de Cloud Run necesita |
| `roles/cloudscheduler.admin` | El cron de fetch-intel (§6.2 del ADR — Cloud Run no tiene trigger de cron nativo) |
| `roles/secretmanager.admin` | Los 5 secrets de runtime, mismo contenido que en Azure |
| `roles/storage.admin` | Leer/escribir el bucket de state de Terraform (§3) |

**Verificación**: `gcloud projects get-iam-policy ... --filter=...`
lista los 5 roles para el Service Account.

---

---

## 6. Módulo Terraform (`infra/gcp/`)

Mismos cinco archivos que `infra/azure/`, adaptados:

- **`backend.tf`** — apunta al bucket de §3.
- **`providers.tf`** — provider `google ~> 6.0`.
- **`variables.tf`** — mismos 5 secrets de runtime que Azure, más
  `ghcr_username`/`ghcr_token` para el espejo de Artifact Registry
  (§Alternativas descartadas de ADR-0022), y `image_repository`/`image_tag`
  en vez de una sola `image` (Cloud Run pull-ea de un repo propio, no
  directo de GHCR).
- **`main.tf`** — Service Account de runtime (distinto del de GitHub
  Actions), los 5 secrets en Secret Manager, el espejo de Artifact
  Registry hacia `ghcr.io`, el Cloud Run service (`min_instance_count=0`),
  los 3 Cloud Run Jobs, y Cloud Scheduler + su propio Service Account
  para el cron de fetch-intel.
- **`outputs.tf`** — `api_url`, `project_id`, `ghcr_mirror_repository`.

### Bug real encontrado por `terraform validate` (no por un `apply`, esta vez)

`for_each` sobre un mapa cuyos *valores* son sensibles (`local.secrets`,
con las 5 claves de runtime) — Terraform lo rechaza de plano: expone las
claves del mapa como identificador de recurso en el state, y no puede
garantizar que esas claves no filtren el contenido sensible. A
diferencia del bug del secret vacío en Azure (que sólo apareció en un
`apply` real), este lo atrapó `terraform validate`, sin tocar la nube.

Arreglado separando `secret_ids` (las claves — "existe un secret
llamado `database-url`", no sensible) de `secret_values` (los valores —
sí sensibles): el `for_each` sólo itera sobre el primero,
`local.secret_values[each.key]` se indexa recién dentro del recurso.
`nonsensitive()` marca explícitamente que **si** LangSmith está
configurado no es en sí mismo un secreto — la clave real sigue
sensible, sólo se declara segura la pregunta "¿existe o no?".

### `terraform plan` de prueba, contra la API real de GCP

```bash
terraform plan \
  -var="ghcr_username=Nicolas-Torres" \
  -var="ghcr_token=placeholder-pat-read-packages" \
  -var="database_url=postgresql://placeholder" \
  -var="anthropic_api_key=placeholder" \
  -var="gemini_api_key=placeholder"
```

**Resultado**: `Plan: 22 to add, 0 to change, 0 to destroy` — sin
errores, contra el backend real (`terraform init` completo, no
`-backend=false`).

**Punto a confirmar recién en el `apply` real, no antes**: el plan
muestra `docker_repository { public_repository = "DOCKER_HUB"
custom_repository { uri = "https://ghcr.io" } }` — el schema del
provider trae `public_repository` con un default (`DOCKER_HUB`) que
convive con `custom_repository` en la misma respuesta de plan. No es
necesariamente un error (`custom_repository` puede simplemente
prevalecer), pero es exactamente el tipo de cosa que sólo la API real
de Artifact Registry confirma — igual que el secret vacío de Azure,
documentado acá antes de que se sepa el resultado, no después.

**Pendiente antes de un `apply` real**: valores genuinos de los 5
secrets (mismos que ya usa Azure, reusables) y un PAT de GitHub con
`read:packages` para el espejo de Artifact Registry (puede ser el mismo
patrón que el de Azure, pero un token propio — el que se usó para Azure
en su momento no quedó guardado en ningún lado, por diseño).

## 7. `terraform apply` real — dos bugs encontrados, ambos resueltos

Con los secrets reales (mismos valores que Azure, más un PAT de GitHub
nuevo y propio — `read:packages`, mismo criterio de no reusar
identidades entre nubes) se corrió el `apply` real.

### Bug 1: Artifact Registry usa su propia identidad para leer credenciales

El primer intento creó 16 recursos y falló creando el repository:

```
Error 400: An error occurred while retrieving upstream credentials:
Artifact Registry service account
"service-432475042270@gcp-sa-artifactregistry.iam.gserviceaccount.com"
does not have permission to access the secret version.
```

Causa: cuando Artifact Registry necesita leer las credenciales del
upstream (para el espejo hacia GHCR), lo hace con **su propia
identidad de servicio gestionada por Google** —una por proyecto,
`service-<projectNumber>@gcp-sa-artifactregistry.iam.gserviceaccount.com`—,
no con la identidad que corrió el `apply`. Nunca hizo falta crearla a
mano (la provisiona Google en cuanto se usa la API), pero sí darle
permiso explícito sobre el secret `ghcr-token`:

```hcl
resource "google_secret_manager_secret_iam_member" "artifact_registry_ghcr_pull" {
  secret_id = google_secret_manager_secret.this["ghcr-token"].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:service-${data.google_project.current.number}@gcp-sa-artifactregistry.iam.gserviceaccount.com"
}
```

Con `depends_on` explícito en el repository — no hay ninguna referencia
de atributo entre ambos recursos que le indique a Terraform el orden
por sí solo.

### Bug 2: Cloud Run enruta al puerto 8080 por defecto, no al que declara la app

Con el fix anterior, el `apply` completó los 10 recursos restantes —
pero `/health`/`/ready` daban `500` con `server: Google Frontend`
(nunca llegaban a la app). Los logs de sistema de Cloud Run (no los de
la app) lo dijeron directo:

```bash
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="fraud-detection-api" AND severity>=WARNING' \
  --limit=20 --format="value(timestamp,severity,textPayload)"
# ERROR  The request timed out while connecting to the instance.
```

Los `startup_probe`/`liveness_probe` sí pasaban (cada uno declara su
propio puerto, 8000) — pero nunca declaré el puerto real del
**contenedor**, y Cloud Run enruta el tráfico real al 8080 por defecto
si no se le dice lo contrario. Fix de una línea:

```hcl
containers {
  # ...
  ports {
    container_port = 8000
  }
}
```

**Verificación, después de ambos fixes**:

```bash
curl .../health     # 200
curl .../ready      # 200
curl .../api/v1/cases/showcase
# los mismos 5 case_id que ya devuelve Azure — misma Neon, confirmado
# desde una nube distinta, sin ningún cambio extra
```

**Lección**: un `startup_probe` que pasa no prueba que el tráfico real
vaya a llegar — sólo prueba que *ese* puerto, con *esa* ruta, responde
cuando Cloud Run mismo lo pregunta. El puerto que de verdad importa
para el tráfico de un visitante es una configuración aparte.

---

## 8. Fase 6 — workflow de CD (`deploy-gcp.yml`)

Mismo patrón que `deploy-azure.yml`: `workflow_run` tras `CI`, mismo
`sha-<7>` calculado del commit, migrar (aborta si falla) → servir →
sembrar (no bloqueante) → mantener fetch-intel al día. Diferencia real
frente a Azure: `gcloud run jobs execute --wait` bloquea hasta que la
ejecución termina y devuelve el código de salida real — no hizo falta
el loop de sondeo manual (`until ... az containerapp job execution
show ...`) que sí hizo falta en `deploy-azure.yml`.

Login con `google-github-actions/auth@v2` (Workload Identity
Federation) — dos secrets nuevos en GitHub, cargados vía API con el
mismo método que los de Azure (`pynacl.SealedBox` contra la public key
del repo):

```bash
GCP_WORKLOAD_IDENTITY_PROVIDER = projects/432475042270/locations/global/workloadIdentityPools/github-actions-pool/providers/github-actions-provider
GCP_SERVICE_ACCOUNT            = github-actions-deployer@fraud-detection-portafolio.iam.gserviceaccount.com
```

**Nota**: el `workload_identity_provider` necesita el **número** de
proyecto (`432475042270`), no el `project_id` — a diferencia de casi
todo lo demás en `gcloud`, que acepta el id.

<!-- Sigue con: 1) primera corrida real disparada por un push a main,
2) acta de cierre de Fase 6. -->
