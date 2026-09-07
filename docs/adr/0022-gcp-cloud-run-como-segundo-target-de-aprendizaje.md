# ADR-0022: GCP Cloud Run como segundo target de despliegue, a modo de aprendizaje

- **Estado**: aceptado
- **Fecha**: 2026-09-07

## Contexto

ADR-0021 decidió Azure Container Apps como orquestador principal y dejó
GCP explícitamente fuera de alcance: "es un objetivo de aprendizaje
declarado, secuenciado después de que Azure funcione de punta a punta
con evidencia — se decide y se documenta en un ADR propio cuando llegue
esa fase". Esa fase es esta: Azure ya tiene infraestructura real
(`rg-fraud-detection`), CI/CD automático verificado dos veces con
código real (docs/reviews/11-ci-cd-azure.md), y el bug de la vitrina
horneada en el build resuelto de raíz (PR #28).

El pedido de multi-nube "a modo de aprendizaje" venía desde la
discusión de ADR-0021 —es parte de por qué se eligió Terraform en
primer lugar, en vez de un mecanismo específico de un solo proveedor—.
Esta fase no reemplaza nada de Azure: agrega un segundo target que
demuestra el mismo módulo declarado en Terraform aplicado a otra nube,
sin competir por tiempo ni por criticidad con la demo principal del
portafolio.

## Decisión

El segundo orquestador es **Cloud Run**, declarado con **Terraform**
(`google`, estado remoto en Cloud Storage desde el primer commit,
mismo principio que Azure).

Los cuatro modos de arranque de la imagen (contrato §1.2) se mapean
así:

| Modo | Recurso de GCP |
|---|---|
| Servir (`uvicorn`) | Cloud Run service, `min_instance_count: 0` — escala a cero, a diferencia de Azure |
| Migrar (`alembic upgrade head`) | Cloud Run Job, disparo manual desde el pipeline de CD |
| Sembrar (`seed.py`) | Cloud Run Job, disparo manual desde el pipeline de CD, después del de migrar |
| Fetch-intel | Cloud Run Job + Cloud Scheduler (GCP no tiene trigger de cron nativo en el recurso Job) |

**Escala a cero, a propósito — a diferencia del `min-replicas: 1` de
Azure.** Este despliegue es la demo *secundaria*, de aprendizaje: la
que está enlazada en el README y que un evaluador va a visitar primero
sigue siendo Azure. Un cold-start ocasional acá es aceptable a cambio
de no duplicar el costo fijo mensual del portafolio — con
`min_instance_count: 0`, Cloud Run sólo cobra cómputo mientras
atiende una request real. Es el mismo criterio de "costo moderado" de
ADR-0021 §Contexto, aplicado distinto porque esta vez el 24/7 no es un
requisito: nadie evalúa una postulación mirando primero la demo de
GCP.

**Misma base, Neon, sin cambios.** Ya decidido en ADR-0021
precisamente para este escenario: la base es neutral a la nube, así
que un segundo proveedor de cómputo no obliga a replicar datos. Los
cinco secrets de runtime (incluido `DATABASE_URL`) son los mismos
valores que ya usa Azure, cargados en el proveedor de secretos nativo
de GCP (Secret Manager) en vez del de Container Apps.

**Misma imagen de GHCR — sin Artifact Registry, sin segundo build.**
ADR-0008 ya fija GHCR como el único registro; agregar un registro de
GCP duplicaría el pipeline de CI para el mismo artefacto. Cloud Run
puede desplegar una imagen de un registro externo con credenciales —el
mecanismo exacto (basic auth directo vs. un remote repository de
Artifact Registry como *pull-through cache*) se resuelve en la
práctica durante la implementación, no se cierra de antemano acá.

**Autenticación de GitHub Actions hacia GCP: Workload Identity
Federation, no una clave de Service Account.** Mismo principio que el
OIDC de Azure (ADR-0021): un Workload Identity Pool + Provider
configurado para confiar en tokens OIDC de GitHub Actions acotados a
este repo, que impersonan un Service Account de vida corta por
corrida. Nunca una clave JSON de Service Account descargada y guardada
como secret — es exactamente la superficie de robo permanente que
ADR-0021 ya rechazó para Azure.

**Estado de Terraform: remoto desde el primer commit.** Un bucket de
Cloud Storage dedicado, creado una sola vez a mano — misma razón que el
Storage Account de Azure: el backend remoto tiene que existir antes de
que haya un Terraform que lo gestione.

## Alternativas descartadas

**GKE Autopilot.** Es la opción de GCP más parecida a "Kubernetes real"
y la más tentadora si el aprendizaje buscado fuera específicamente
Kubernetes. Se descarta con el mismo argumento que ADR-0021 ya usó
contra AKS: aunque Autopilot factura por pod en vez de por nodo (sin el
piso fijo de un control plane clásico), sigue exigiendo el mismo nivel
de operación conceptual —namespaces, RBAC, un objeto de ingress— que
Cloud Run evita por completo al ser serverless, para un proyecto que no
necesita esa superficie.

**Artifact Registry con espejo de la imagen.** Mantener una copia de la
imagen en Artifact Registry (en vez de que Cloud Run tire directo de
GHCR) simplificaría la autenticación a costa de un segundo lugar donde
la imagen puede desincronizarse del digest real que CI publicó. Se
prueba primero el camino directo a GHCR; si resulta inviable en la
práctica, un *remote repository* de Artifact Registry (que sigue
apuntando a GHCR como fuente, no una copia manual) es la salida, no una
imagen duplicada.

**Cloud Functions / App Engine.** Ninguno de los dos corre un
contenedor Docker arbitrario con el mismo modelo de las cuatro
"formas de arrancar" que ya fija el contrato (§1.2) — habría que
adaptar el empaquetado en vez de reusarlo tal cual, perdiendo la
premisa de "una imagen, cuatro modos" en el segundo proveedor.

## Consecuencias

**Se gana** evidencia real de multi-nube con el mismo Terraform,
mismo Dockerfile, mismo pipeline de CI hasta el build — sólo el módulo
de cómputo y el workflow de CD son específicos de cada nube; un
despliegue casi gratuito en reposo (`min_instance_count: 0`) que no
duplica el gasto fijo mensual del portafolio; y una segunda base de
comparación real de costo/operación entre dos nubes serverless para el
informe.

**Se paga:**

- **Cold-start real en la primera visita después de inactividad.**
  Aceptado a propósito (ver Decisión) — no es la demo que un evaluador
  visita primero.
- **Cloud Scheduler es una pieza que Azure no necesitaba.** El Job de
  fetch-intel de Azure tiene su propio `schedule_trigger_config`
  nativo; en Cloud Run hace falta un recurso aparte (`google_cloud_scheduler_job`)
  invocando la Admin API del Job — más superficie declarada en
  Terraform para el mismo resultado.
- **El módulo de cómputo de GCP tampoco es reusable si algún día se
  migra de nube por completo** — mismo argumento que ADR-0021 §Consecuencias
  aplicado a la inversa: cada proveedor de cómputo tiene su propio
  Terraform, sólo el Dockerfile y el CI hasta el build son comunes a
  los dos.
- **Dos proveedores de cómputo activos duplican la superficie de
  mantenimiento** (dos módulos Terraform, dos workflows de CD, dos
  identidades OIDC/Workload Identity a rotar/auditar) a cambio de la
  evidencia de aprendizaje que se buscaba desde el principio.
