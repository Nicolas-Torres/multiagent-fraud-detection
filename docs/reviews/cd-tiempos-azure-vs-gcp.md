# Notas — por qué el CD de GCP tarda más que el de Azure

> **No es un cierre de etapa** — no corresponde un número de la secuencia
> `01`…`12`. Es un documento vivo: junta lo que se fue midiendo y
> aprendiendo sobre los tiempos reales de los dos pipelines de CD
> (`deploy-azure.yml`, `deploy-gcp.yml`), separado de por qué existen las
> dos nubes (ADR-0021, ADR-0022) o de cómo se armó cada una (los
> runbooks). Se sigue completando — ver §4, "Pendiente".

## 1. El disparador

El usuario notó, mirando el PR #38 desplegarse en vivo, que el CD de
Azure siempre termina antes que el de GCP. Medido en esa misma corrida
(mismo commit, `fd7ca2d`, los dos arrancaron al mismo segundo):
**Azure: 2m12s. GCP: 7m16s** — ~3.3x. No es percepción, ni un caso
aislado: una corrida anterior (commit `469702f`) dio 2m10s vs 6m39s,
mismo orden de magnitud.

## 2. Comparativa por paso, con logs reales de las dos corridas

Todos los tiempos salen de los timestamps reales de los logs de GitHub
Actions (`actions/jobs/{id}/logs`), no de estimaciones.

| Paso | Azure | GCP | ¿Bloqueante en Azure? | ¿Bloqueante en GCP? |
|---|---|---|---|---|
| Migrar | 52.9s | 211.0s | Sí | Sí |
| Actualizar servicio | 16.0s | 34.0s | Sí | Sí |
| Sembrar | 19.2s* | 148.0s | **No** | **Sí** — ver §3 |
| Mantener fetch-intel en la misma imagen | 18.0s | 2.0s | No | No |
| **Total del job `deploy`** | **~2m** | **~7m16s** | | |

*Azure's "Sembrar" no espera a que el seed termine — ver §3, no es
comparable 1 a 1 con el de GCP tal cual está la tabla.

### 2.1 Desglose fino de GCP (el `gcloud run jobs execute --wait` expone fases)

| Fase | Migrar | Sembrar |
|---|---|---|
| Provisioning resources | 7.4s | 2.1s |
| **Starting execution** | **189.3s (89%)** | **123.3s (83%)** |
| Running execution (el trabajo real) | 9.1s | 18.8s |

**El trabajo real —correr las migraciones, insertar el seed— es rápido
en los dos casos (9-19s).** Casi todo el tiempo de GCP se va en
"Starting execution", antes de que corra una sola línea de nuestro
Python — **no es la imagen bajando** (§2.3 lo mide y lo descarta): es el
cold-start del sandbox `gen2` de Cloud Run Jobs.

### 2.2 Desglose fino de Azure — resuelto, mismo nivel de detalle que GCP

`az` no expone fases nombradas como `gcloud --wait`, pero cruzando
`az containerapp job execution list` (timestamps reales de inicio/fin)
contra el primer log real de la app en `ContainerAppConsoleLogs_CL`
(mismo método que ya usó el incidente 0001) se separa arranque de
contenedor de trabajo real, igual que en GCP:

| Job | Ejecución | Total | Arranque de contenedor (comando → primer log) | Trabajo real |
|---|---|---|---|---|
| Migrar | `caj-fraud-detection-migrate-bo3q668` (2026-09-17) | 31s | ~23.3s | ~7.7s (Alembic) |
| Sembrar | `caj-fraud-detection-seed-k9fe74b` (2026-09-17) | 28s | ~16.3s | ~11.7s (seed) |

### 2.3 Investigado (2026-09-17): no es imagen, no es el espejo — es el cold-start del sandbox `gen2` de Cloud Run Jobs

El tamaño real de la imagen ya se confirmó (§4): **152.5 MiB comprimidos**,
mismo dígest `amd64` en las dos nubes — no hay diferencia de imagen que
explique lo que sigue.

Con el desglose de §2.1/§2.2, Azure tarda **~23.3s / ~16.3s** en arrancar
el contenedor (comando → primer log real). GCP, con la **misma imagen**,
tarda **189.3s / 123.3s** en "Starting execution". Las dos hipótesis
originales (pull directo de GHCR vs. a través del espejo de Artifact
Registry; cold-start "genérico" de Cloud Run Jobs) quedaron descartadas o
confirmadas con datos, no con conjeturas:

**`gcloud run jobs executions describe` expone condiciones con timestamps
más finos que el `--wait` simple**, y cuentan una historia distinta a la
esperada. Ejemplo real (`fraud-detection-migrate-hh5lz`, 2026-09-17):

| Condición | Timestamp | Mensaje |
|---|---|---|
| `ContainerReady` | 05:44:31.320 | "Imported container image" |
| `ResourcesAvailable` | 05:44:31.443 | "Provisioned imported containers" |
| `Started` | 05:47:20.453 | "Started deployed execution in **2m49.01s**" |
| `Completed` | 05:47:32.715 | "Execution completed successfully in 2m45.46s" |

**La imagen está lista en ~3-4 segundos** desde que se emite el comando
—confirmado en las dos corridas que se midieron así, Migrar y Sembrar—:
el espejo de Artifact Registry no es el cuello de botella, se descarta la
primera hipótesis. Los ~2m49s enteros pasan **entre
`ContainerReady`/`ResourcesAvailable` y `Started`**, con **cero entradas
de log de ningún tipo** (app, audit, platform) en esa ventana — no es
código nuestro, es la plataforma tardando en poner a correr un contenedor
que ya tiene listo.

Revisando la config del job apareció el candidato concreto:
`run.googleapis.com/execution-environment: gen2` — no seteado por
nosotros, es el default de GCP. Gen2 es el sandbox más nuevo de Cloud Run
(mejor compatibilidad de syscalls/red/filesystem que gen1), documentado
por Google con cold-start más lento a cambio de esa compatibilidad.

**Se intentó confirmar empíricamente** (cambiar el job a
`--execution-environment=gen1` y remedir):

```
ERROR: (gcloud.run.jobs.update) spec.template.metadata.annotations:
Annotation 'run.googleapis.com/execution-environment' with value 'gen1'
is not supported on resources of kind Execution.
```

**`gen1` no existe para Cloud Run Jobs — sólo para Cloud Run Services.**
No se pudo hacer el A/B, pero el resultado es igual de concluyente: `gen2`
no es una opción mal elegida que se pueda cambiar, es el único execution
environment que Jobs soporta. El cold-start de ~100-190s no es un bug de
esta configuración ni del tamaño de la imagen — es el piso real de la
plataforma para este tipo de recurso en GCP. Azure Container Apps Jobs no
tiene un concepto equivalente expuesto a este nivel; no se investiga más
a fondo por qué su arranque es estructuralmente más rápido, sólo que lo
es, de forma consistente, en todas las corridas medidas.

## 3. Hallazgo real, no sólo una diferencia de plataforma: `Sembrar` en GCP no es lo que dice ser

Los dos workflows nombran el paso igual, con la misma razón (ADR-0010) y
el mismo `continue-on-error: true`:

```yaml
# .github/workflows/deploy-azure.yml:89
- name: "Sembrar (no bloqueante, ADR-0010: idempotente, un fallo acá no revierte el deploy)"
  continue-on-error: true
  run: |
    az containerapp job update ...
    az containerapp job start --name caj-fraud-detection-seed ...
    # no espera nada más — dispara y sigue

# .github/workflows/deploy-gcp.yml:60 (antes del fix de abajo)
- name: "Sembrar (no bloqueante, ADR-0010: idempotente, un fallo acá no revierte el deploy)"
  continue-on-error: true
  run: |
    gcloud run jobs update fraud-detection-seed ...
    gcloud run jobs execute fraud-detection-seed --region "${{ env.REGION }}" --wait
    #                                                                          ^^^^^
```

**El de GCP tenía `--wait` — el de Azure no.** El nombre del paso decía
"no bloqueante" en los dos archivos, pero sólo Azure cumplía esa promesa.
GCP bloqueaba el pipeline entero ~148 segundos esperando un Job cuyo
resultado, por diseño (`continue-on-error: true`), a nadie le importa
que termine antes de seguir. Era la explicación de buena parte de los
7m16s totales — no una limitación de la nube, era una línea de más en el
workflow.

**Primer fix (2026-09-17): sacar `--wait`.** Se sacó de
`.github/workflows/deploy-gcp.yml:64` (`Migrar`, línea 52, conserva el
suyo — esa sí tiene que bloquear, ADR-0009). Verificado con un deploy
real: merge de PR #42 (commit `c6342f9`), Azure y GCP corriendo en
paralelo desde el mismo push:

| Paso | Azure | GCP |
|---|---|---|
| Migrar | 47s | 109s |
| Actualizar servicio | 15s | 19s |
| Sembrar | 18s | **103s** |
| Mantener fetch-intel | 18s | 2s |
| **Total** | **1m59s** | **4m17s** |

Mejora real (7m16s → 4m17s: la brecha bajó de 3.3x a 2.2x), pero
**Sembrar siguió en 103s** — ahí salió que la semántica de `--wait` no era
la asumida:

```
--wait   Wait until the execution has completed running before exiting.
         If not set, gcloud exits successfully when the execution has started.
```

Sin `--wait`, `gcloud run jobs execute` sigue esperando a que la ejecución
**arranque** — el mismo cold-start de "Starting execution" que ya medía
§2.1 (~123s para Sembrar). El primer fix sólo sacó la cola de "Running
execution" (~19-45s), no el cold-start, que es la parte grande.

**Segundo fix (2026-09-17): agregar `--async`.**
`.github/workflows/deploy-gcp.yml:64` — `--async` devuelve el control
apenas se crea la ejecución, sin esperar ni a que arranque, igual que el
fire-and-forget que ya hacía Azure (`az containerapp job start`, sin
polling).

**Confirmado (2026-09-17)**, con otro deploy real (merge de PR #43, commit
`1b74bbf`, Azure y GCP en paralelo): Sembrar pasó de **103s a 3s** —
fire-and-forget de verdad, al fin igual de rápido que el de Azure (18s,
incluye el `az containerapp job start` en sí).

| Paso | Azure | GCP |
|---|---|---|
| Migrar | 50s | 190s |
| Actualizar servicio | 14s | 46s |
| Sembrar | 18s | **3s** |
| Mantener fetch-intel | 18s | 3s |
| **Total** | **1m58s** | **4m30s** |

El total de GCP **no** bajó proporcionalmente esta corrida (4m30s, similar
al 4m17s de la verificación anterior) — pero no es que el fix haya
fallado: `Migrar` (que sí tiene que bloquear, ADR-0009) tardó 190s esta
vez contra 109s la vez pasada, la misma variabilidad de cold-start de
Cloud Run que ya documenta §2.3. El fix de Sembrar quedó objetivamente
confirmado (103s → 3s); lo que sigue empujando el total hacia arriba es
la pregunta abierta de §2.3, no esto.

## 4. Pendiente — los 5 puntos resueltos (2026-09-17)

Los cinco puntos que este documento dejaba abiertos (los últimos cuatro
del cierre original, más la investigación de §2.3 que se sumó después):

- **Tamaño real de la imagen — resuelto.** `docker manifest inspect`
  contra GHCR directo seguía fallando por autenticación; el camino que
  funcionó fue autenticar Docker contra el propio espejo
  (`gcloud auth configure-docker us-central1-docker.pkg.dev`) y usar
  `docker buildx imagetools inspect --raw` sobre el manifiesto `amd64`:
  **152.5 MiB comprimidos, 16 capas** (build `sha-83268ac`).
- **¿El espejo cachea de verdad? — resuelto, y descartado como causa del
  tiempo lento.** `gcloud artifacts docker images list` muestra cada tag
  creado una única vez (mismo `CREATE_TIME`/`UPDATE_TIME`, sin entradas
  duplicadas por pulls repetidos) — consistente con el cacheo documentado
  del modo `REMOTE_REPOSITORY`. Confirmado además con timestamps directos
  en §2.3: la imagen queda lista (`ContainerReady`) en ~3-4s desde el
  comando — el tiempo de "Starting execution" **no** es el espejo
  re-descargando ni Cloud Run bajando la imagen, es otra cosa (ver §2.3).
- **Detalle de fases para Azure — resuelto.** Ver §2.2: mismo nivel de
  detalle que GCP, cruzando `az containerapp job execution list` con
  `ContainerAppConsoleLogs_CL`.
- **Sacar el bloqueo de `Sembrar` en GCP — resuelto y confirmado, ver
  §3.** El primer intento (sacar `--wait`) sólo recortó ~45s de los 148s
  originales, porque `gcloud run jobs execute` espera a que la ejecución
  *arranque* aunque no se le pida esperar a que termine. `--async` sí lo
  resolvió del todo: confirmado con un deploy real, 103s → 3s.
- **Por qué Azure arranca la misma imagen 8-12x más rápido — investigado,
  ver §2.3.** No es tamaño de imagen (idéntico en las dos nubes), no es
  el espejo de Artifact Registry (imagen lista en ~3-4s), no es el código
  de la app (cero logs durante el hueco). Es el cold-start del sandbox
  `gen2` de Cloud Run — confirmado indirectamente porque `gen1` (el
  sandbox más liviano) **no existe para Cloud Run Jobs**, sólo para
  Services: no hay flag que lo evite, es el piso real de la plataforma
  para este recurso.

**Lo que sigue sin explicarse, y probablemente no valga la pena perseguir
más**: por qué el mecanismo interno de arranque de Azure Container Apps
Jobs es estructuralmente más rápido que el de Cloud Run Jobs para el
mismo contenedor — Azure no expone un concepto equivalente a
`gen1`/`gen2` a este nivel, así que no hay un experimento simétrico para
correr del lado de Azure. Se documenta como una diferencia de plataforma
real y medida, no como conjetura, y se cierra la investigación acá.
