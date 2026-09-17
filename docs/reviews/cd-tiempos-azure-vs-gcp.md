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
"Starting execution": Cloud Run Jobs bajando y arrancando el
contenedor, antes de que corra una sola línea de nuestro Python.

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

### 2.3 Hallazgo nuevo: Azure arranca la misma imagen 8-12x más rápido — pregunta abierta

El tamaño real de la imagen ya se confirmó (§4): **152.5 MiB comprimidos**,
mismo dígest `amd64` en las dos nubes — no hay diferencia de imagen que
explique lo que sigue.

Con el desglose de arriba, Azure tarda **~23.3s / ~16.3s** en arrancar el
contenedor (comando → primer log real). GCP, con la **misma imagen**, tarda
**189.3s / 123.3s** en "Starting execution" (§2.1). Es una diferencia de
**8 a 12 veces**, no explicable por tamaño de imagen porque el tamaño es
idéntico en los dos casos.

Dos hipótesis, ninguna confirmada todavía: Azure Container Apps Jobs tira
la imagen directo de GHCR, mientras que Cloud Run Jobs tira a través del
espejo de Artifact Registry (§4) — o es, más llanamente, que el cold-start
de Cloud Run Jobs es estructuralmente más lento que el de Container Apps
Jobs para este tamaño de imagen. Queda como pregunta abierta genuina, no
se investiga más en esta pasada (ver §4, Pendiente).

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
polling). Pendiente de verificar con el próximo deploy real (§4).

## 4. Pendiente — resuelto (2026-09-17), con una pregunta nueva que queda abierta

Los cuatro puntos que este documento dejaba abiertos:

- **Tamaño real de la imagen — resuelto.** `docker manifest inspect`
  contra GHCR directo seguía fallando por autenticación; el camino que
  funcionó fue autenticar Docker contra el propio espejo
  (`gcloud auth configure-docker us-central1-docker.pkg.dev`) y usar
  `docker buildx imagetools inspect --raw` sobre el manifiesto `amd64`:
  **152.5 MiB comprimidos, 16 capas** (build `sha-83268ac`).
- **¿El espejo cachea de verdad? — resuelto.** `gcloud artifacts docker
  images list` muestra cada tag creado una única vez (mismo
  `CREATE_TIME`/`UPDATE_TIME`, sin entradas duplicadas por pulls
  repetidos) — consistente con el cacheo documentado del modo
  `REMOTE_REPOSITORY`. El tiempo de "Starting execution" es Cloud Run
  bajando la imagen al nodo de ejecución, no el espejo re-descargando de
  GHCR en cada corrida.
- **Detalle de fases para Azure — resuelto.** Ver §2.2: mismo nivel de
  detalle que GCP, cruzando `az containerapp job execution list` con
  `ContainerAppConsoleLogs_CL`.
- **Sacar el `--wait` de `Sembrar` en GCP — parcialmente resuelto, ver
  §3.** El primer intento (sacar `--wait`) sólo recortó ~45s de los 148s
  originales, porque `gcloud run jobs execute` espera a que la ejecución
  *arranque* aunque no se le pida esperar a que termine. Se agregó
  `--async` como segundo fix — **falta confirmar con el próximo deploy
  real** que ahora sí Sembrar es fire-and-forget de verdad (unos pocos
  segundos, no ~100s).

**Lo que queda genuinamente abierto**: el hallazgo de §2.3 (con el tamaño
de imagen ya descartado como variable, Azure arranca el mismo contenedor
8-12x más rápido que GCP) y la confirmación del fix con `--async` de
arriba. Candidatos para cuando se retome: comparar el tiempo de pull
directo desde GHCR (Azure) contra pull desde el espejo de Artifact
Registry (GCP) de forma aislada, o revisar si Cloud Run Jobs tiene algún
parámetro de cold-start/concurrencia que Container Apps Jobs no necesita.
