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

### 2.2 Desglose de Azure — más grueso, `az` no expone las mismas fases

El log de Azure no imprime fases nombradas como el de `gcloud`; sólo se
puede medir "cuánto tarda el comando en devolver el nombre de la
ejecución" y "cuánto tarda el polling hasta que el estado es terminal":

| Tramo | Migrar |
|---|---|
| Comando emitido → nombre de ejecución conocido | 22.3s |
| Ejecución conocida → `Succeeded` (polling manual) | 30.6s |
| **Total** | **52.9s** |

No se puede separar, con este log, cuánto de esos 30.6s es arranque del
contenedor y cuánto es el trabajo real de Alembic — a diferencia de
GCP, donde `--wait` sí lo expone. Queda anotado como pendiente (§4).

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

# .github/workflows/deploy-gcp.yml:60
- name: "Sembrar (no bloqueante, ADR-0010: idempotente, un fallo acá no revierte el deploy)"
  continue-on-error: true
  run: |
    gcloud run jobs update fraud-detection-seed ...
    gcloud run jobs execute fraud-detection-seed --region "${{ env.REGION }}" --wait
    #                                                                          ^^^^^
```

**El de GCP tiene `--wait` — el de Azure no.** El nombre del paso dice
"no bloqueante" en los dos archivos, pero sólo Azure cumple esa promesa.
GCP bloquea el pipeline entero 148 segundos esperando un Job cuyo
resultado, por diseño (`continue-on-error: true`), a nadie le importa
que termine antes de seguir. Es la explicación de buena parte de los
7m16s totales — no una limitación de la nube, es una línea de más en el
workflow.

## 4. Pendiente — profundizar antes de sacar conclusiones definitivas

- **Confirmar el tamaño real de la imagen** en el espejo de Artifact
  Registry. Se intentó con `docker manifest inspect` contra GHCR
  directo y falló por autenticación — hace falta credenciales de GHCR a
  mano o correrlo con `gcloud artifacts docker images describe` con el
  formato correcto (el intentado no devolvió tamaño).
- **Verificar si el espejo de Artifact Registry (`ghcr-mirror`,
  `REMOTE_REPOSITORY`, `infra/gcp/main.tf`) está cacheando de verdad**
  o si cada ejecución de un Job re-descarga la imagen completa desde
  GHCR a través del *pull-through cache* — eso explicaría gran parte de
  "Starting execution" siendo tan largo y tan variable entre corridas
  (189s vs 123s para el mismo tipo de operación, misma imagen).
- **Conseguir el mismo nivel de detalle de fases para Azure** que
  `gcloud --wait` da gratis, para poder comparar arranque-de-contenedor
  contra trabajo-real de forma pareja en las dos nubes — necesita mirar
  Log Analytics (timestamp del primer log de la app vs. timestamp de
  creación de la réplica) o campos más finos de
  `az containerapp job execution show`.
- **Decidir si sacar el `--wait` de `Sembrar` en GCP** (§3) para que
  quede igual de no-bloqueante que en Azure y que el pipeline no pague
  esos ~148s de más en cada deploy — cambio chico, bajo riesgo, pero se
  deja para cuando el usuario lo pida explícito, no se toca en este
  documento.
