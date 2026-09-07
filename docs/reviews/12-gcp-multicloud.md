# Repaso — Etapa "GCP como segundo target (multi-nube)"
**Sistema Multi-Agente de Detección de Fraude · handoff de continuidad**

> Documento de cierre de etapa. Destila lo decidido y construido en la
> rama `feature/ci-cd-gcp`, para retomar en el chat siguiente con el
> contexto ya condensado.
>
> Predecesor: `11-ci-cd-azure.md`.
> Decisión de fondo: [ADR-0022](../adr/0022-gcp-cloud-run-como-segundo-target-de-aprendizaje.md).
> Bitácora comando-por-comando, completa: [`docs/runbook_gcp_setup.md`](../runbook_gcp_setup.md).

---

## 1. Qué se cerró en esta etapa

Un segundo despliegue real, en una nube distinta, del mismo sistema —
explícitamente de aprendizaje (ADR-0022), sin reemplazar a Azure como
demo principal del portafolio.

| Pieza | Archivo | Verificado |
|---|---|---|
| ADR de la decisión, con alternativas descartadas | `adr/0022-*.md` | — |
| Proyecto GCP nuevo y dedicado, billing, APIs, bucket de state | bootstrap manual | `docs/runbook_gcp_setup.md` §0-3 |
| Workload Identity Federation (equivalente GCP del OIDC de Azure) | bootstrap manual | §4 |
| Módulo Terraform: Cloud Run (`min_instance_count=0`) + 3 Jobs + Cloud Scheduler | `infra/gcp/*.tf` | `terraform plan`/`apply` reales, 25/25 recursos creados |
| Espejo de Artifact Registry hacia GHCR (Cloud Run no pull-ea un registro externo directo) | `infra/gcp/main.tf` | resuelto en la práctica, documentado |
| CD: `deploy-gcp.yml` | `.github/workflows/deploy-gcp.yml` | corrida real de punta a punta, dos veces (una con reintento) |
| Infraestructura real, escala a cero | Cloud Run, `fraud-detection-portafolio` | `/health`/`/ready` en 200, `GET /cases/showcase` idéntico a Azure |

---

## 2. Lo jugoso: cuatro bugs reales, cuatro identidades distintas

A diferencia de Azure (un bug de secret vacío, uno de puerto por
convención), en GCP los cuatro bugs de esta etapa comparten un patrón
más específico: **cada uno era una identidad de servicio a la que se
le olvidó dar un permiso que sólo hacía falta en el momento exacto en
que algo intentaba usarla.**

1. **`for_each` sobre un mapa con valores sensibles** — atrapado por
   `terraform validate`, sin tocar la nube. Terraform rechaza de plano
   iterar un mapa cuyos *valores* llevan la marca de sensible, porque
   las *claves* quedarían expuestas como identificador de recurso en el
   state. Se resolvió separando `secret_ids` (las claves, no
   sensibles) de `secret_values` (los valores, sí) — `nonsensitive()`
   marca explícitamente que "¿existe esta clave o no?" no es en sí un
   secreto.

2. **Artifact Registry lee las credenciales del upstream con su propia
   identidad** (`service-<projectNumber>@gcp-sa-artifactregistry.iam.gserviceaccount.com`),
   no con la que corrió el `apply`. Sin un `secretAccessor` explícito
   para esa identidad sobre `ghcr-token`, crear el repository fallaba
   con un 400 — atrapado por el primer `apply` real, nunca por
   `plan`.

3. **Cloud Run enruta el tráfico real al puerto 8080 por defecto.**
   Los `startup_probe`/`liveness_probe` declaran su propio puerto (8000)
   y pasaban bien — pero nunca declaré el puerto del *contenedor* en
   sí, así que cualquier visitante real chocaba con "the request timed
   out while connecting to the instance". El servicio se reportaba
   `Ready: true` igual: el problema era de enrutamiento, no de
   arranque.

4. **La identidad de GitHub Actions (`github-actions-deployer`) nunca
   tuvo permiso de lectura sobre el espejo** — sólo se lo dio Terraform
   a la identidad de *runtime*. `gcloud run jobs update --image=...`
   también necesita leer el repositorio para resolver la referencia,
   antes siquiera de que un contenedor intente arrancar. Encontrado en
   la primera corrida real de `deploy-gcp.yml`, no en ningún `plan`.

Los cuatro se resolvieron sin necesitar revertir nada — cada fix fue
agregar el permiso o el atributo puntual que faltaba, re-`apply`ar (o
re-disparar el mismo run de CD fallido), y verificar contra el sistema
real.

---

## 3. Decisiones de fondo y su porqué

Ya están todas en ADR-0022 — no se repiten acá. Un resumen de las que
más valen para el informe:

- **Escala a cero, a propósito.** Es la demo secundaria; Azure sigue
  siendo la enlazada en el README. Con `min_instance_count=0`, el costo
  en reposo es casi nulo — el cold-start ocasional es un costo
  aceptado, no un descuido.
- **Reusa GHCR, nunca un segundo build.** El espejo de Artifact
  Registry es un proxy autenticado, no una copia — la imagen real la
  sigue publicando un solo lugar (ADR-0008).
- **Workload Identity Federation, no una clave de Service Account** —
  mismo principio que el OIDC de Azure, aplicado con el mecanismo
  propio de GCP.

---

## 4. Convenciones nuevas fijadas

- **Una identidad de servicio gestionada por Google (`service-<projectNumber>@gcp-sa-*`)
  puede necesitar permisos propios**, distintos de los de quien corre
  el `apply` — no asumir que un solo Service Account cubre todo el
  ciclo de vida de un recurso.
- **El puerto de los probes y el puerto del tráfico real son
  configuraciones separadas en Cloud Run** — declarar uno no declara
  el otro.
- **La identidad que despliega y la identidad que sirve son dos
  necesidades de permiso distintas**, aunque ambas necesiten leer la
  misma imagen — no alcanza con dársela a una sola.
- **`for_each` no tolera un mapa con valores sensibles** — separar
  claves de valores, `nonsensitive()` sólo sobre lo que genuinamente no
  es secreto (existencia, no contenido).

### Footguns verificados en esta etapa

| Trampa | Detalle |
|---|---|
| `for_each` sobre valores sensibles | Terraform lo rechaza en `validate` — separar claves (no sensibles) de valores (sí), `nonsensitive()` sólo sobre la pregunta de existencia. §2.1 |
| Artifact Registry remote repository | Lee las credenciales del upstream con su propia identidad de servicio gestionada por Google, no con la del `apply`. §2.2 |
| Puerto de Cloud Run | El contenedor necesita un `ports { container_port = ... }` explícito — los probes declaran su propio puerto por separado, y pasar no prueba que el tráfico real vaya a llegar. §2.3 |
| Identidad de deploy vs. identidad de runtime | Ambas necesitan leer la misma imagen, pero son permisos distintos que hay que otorgar por separado. §2.4 |

---

## 5. Hallazgos y deuda

### 5.1 Costo de mantener dos nubes activas

Dos módulos Terraform, dos workflows de CD, dos identidades a rotar y
auditar — ya declarado como consecuencia en ADR-0022. Aceptado a
cambio de la evidencia de aprendizaje.

### 5.2 Resto de deuda, heredada sin cambios

Sin autenticación en los endpoints públicos (acta 09 §6.1, 10 §6.1, 11
§6.4) y la mejora pendiente de retry propio en `internal_policy_rag`
(acta 11 §6.2, tarea #45) — ninguna de las dos es específica de esta
etapa, siguen igual.

---

## 6. Mapa de archivos al cierre

```
.github/workflows/
└── deploy-gcp.yml                      # workflow_run tras CI -> migrar -> servir -> sembrar -> fetch-intel

infra/gcp/
├── backend.tf                          # bucket de GCS (bootstrapeado a mano)
├── providers.tf
├── variables.tf
├── main.tf                             # runtime SA, 5 secrets, espejo de AR, Cloud Run service, 3 Jobs, Scheduler
└── outputs.tf                          # api_url, ghcr_mirror_repository

docs/
├── adr/0022-*.md
├── runbook_gcp_setup.md                # bitácora completa, los 4 bugs incluidos
└── reviews/12-gcp-multicloud.md        # este archivo
```

---

## 7. Qué sigue

Ninguna fase de CI/CD queda pendiente en el plan original. Lo que
sigue, fuera de esta línea de trabajo:

- Tarea #45: retry propio en `internal_policy_rag` (anotada, no
  implementada).
- Tarea #2: explorar migración a `ChatAnthropic`, con su propio ADR.
- Revisión de costo de Azure a ~1 mes de la Fase 3 (fecha de
  referencia: 2026-09-06).

---

## 8. Documentación asociada

- [ADR-0022](../adr/0022-gcp-cloud-run-como-segundo-target-de-aprendizaje.md)
- [`docs/runbook_gcp_setup.md`](../runbook_gcp_setup.md) — la bitácora completa
- `11-ci-cd-azure.md` — etapa anterior
- Demo principal (Azure): https://ca-fraud-detection-api.graywave-cc1ab2d2.eastus2.azurecontainerapps.io
- Demo de aprendizaje (GCP): https://fraud-detection-api-im2rcartea-uc.a.run.app
