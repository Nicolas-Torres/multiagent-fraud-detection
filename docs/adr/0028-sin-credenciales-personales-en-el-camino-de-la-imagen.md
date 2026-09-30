# ADR-0028: sin credenciales personales en el camino de la imagen

- **Estado**: aceptado
- **Fecha**: 2026-09-29
- **Actualiza**: ADR-0022 (el espejo de GHCR pasa a un repositorio propio con
  promoción por digest) y ADR-0023 (el archivo de secretos compartido pasa de 6 a
  5 valores).

## Contexto

El artefacto que se despliega es una imagen que CI publica en GHCR (ADR-0008).
Hasta hoy cada nube la bajaba con **un token personal de GitHub** (PAT
`read:packages`):

| Tramo | Cómo se autentica |
|---|---|
| CI → GHCR (push) | `GITHUB_TOKEN` del workflow: temporal, dura una corrida |
| GitHub Actions → Azure y GCP (deploy) | **OIDC** (`azure/login`, Workload Identity Federation): sin secretos guardados |
| Azure (app y 3 jobs) → GHCR (pull) | **PAT personal**, guardado como secreto `ghcr-token` en la Container App |
| GCP: espejo de Artifact Registry → GHCR | **otro PAT personal**, en Secret Manager |
| Cloud Run → espejo | cuenta de servicio (IAM): sin secretos |

Los dos PAT tienen los problemas de toda credencial personal de larga vida:

- **Vencen**, y cuando vencen fallan los deploys y las ejecuciones de los jobs
  (migrate, seed, fetch-intel), que bajan la imagen en cada corrida.
- **Nadie conoce ya sus valores**: GitHub los muestra sólo al crearlos. Rotarlos
  exige crear otros.
- **Están atados a una persona**: con el scope `read:packages`, cada uno lee todos
  los paquetes de la cuenta, no sólo esta imagen.
- **Bloquean `infra/rotate-secrets.sh`**: Terraform exige los 6 valores del
  archivo compartido en cada `apply`, y sin el token no se puede rotar ningún otro
  secreto, por ejemplo la `DATABASE_URL`, con el mecanismo diseñado para eso.

**Hecho verificado:** la imagen es pública. Un pull anónimo del manifiesto de
`sha-1f4eaa1` devolvió 200, y el repositorio es público: el código es open source.

## Qué es lo estándar

**En una empresa, con código privado**, el patrón es:

1. Un registro privado **en la misma nube** donde corre la app: ACR, Artifact
   Registry o ECR.
2. CI publica ahí **con OIDC**, sin secretos guardados.
3. El runtime baja la imagen **con una identidad administrada** (Managed Identity
   con `AcrPull`, o una cuenta de servicio con `artifactregistry.reader`), sin
   contraseñas.

Si el registro de origen es externo y privado, la credencial hacia él es de una
máquina (GitHub App o bot), se guarda una sola vez en un gestor de secretos y se
rota automáticamente. **Nunca un token personal.**

**En open source**, la imagen se publica y se baja sin credenciales. Aun así, es
habitual copiarla a un registro propio, por disponibilidad, límites de descarga y
control de la cadena de suministro.

## Decisión

**Ninguna credencial personal en el camino de la imagen. Donde el patrón
empresarial es gratis (GCP) se implementa completo; donde no lo es (Azure), se
usa la imagen pública, y el trade-off queda escrito.**

**GCP: patrón empresarial completo.**

- Un repositorio **estándar** de Artifact Registry (`images`, formato DOCKER),
  con política de limpieza que guarda sólo las 3 últimas versiones.
- `deploy-gcp.yml`, después del login OIDC, **promueve la imagen por digest**:
  `crane copy` de `ghcr.io/…:sha-<7>` al repositorio nuevo. El manifiesto se
  copia byte a byte, así que el digest es el mismo que publicó CI y GHCR sigue
  siendo el único origen (ADR-0008). La lectura desde GHCR usa el `GITHUB_TOKEN`
  del workflow: temporal, y sirve igual si la imagen fuera privada.
- Cloud Run y sus jobs bajan la imagen de ese repositorio con la cuenta de
  servicio de runtime. La cuenta de deploy tiene `artifactregistry.writer`, sólo
  sobre ese repositorio.
- Se eliminan el espejo remoto, el secreto `ghcr-token` y su permiso.

**Azure: imagen pública, sin credenciales.**

- La Container App y sus 3 jobs bajan la imagen pública de GHCR sin bloque
  `registry`. Se elimina el secreto `ghcr-token`.
- El patrón empresarial en Azure (ACR con Managed Identity) cuesta ~USD 5 por
  mes, porque ACR no tiene plan gratuito. Para un proyecto de portafolio no se
  justifica.

**Guarda: que la imagen sea pública deja de ser implícito.** CI verifica,
después de cada push, que el tag recién publicado se puede bajar sin
credenciales. Si alguien pasa la imagen o el repositorio a privado, CI falla con
un mensaje que remite a este ADR, antes de que falle un deploy de Azure.

## Alternativas descartadas

| Alternativa | Costo | Por qué no |
|---|---|---|
| PAT clásico **sin vencimiento**, compartido | USD 0 | Una credencial personal permanente, con acceso a todos los paquetes de la cuenta. Si se filtra, sirve para siempre. GitHub advierte en contra; es lo que las políticas de seguridad prohíben |
| PAT con vencimiento, rotado con `rotate-secrets.sh` | USD 0 | Es lo correcto *si* hiciera falta una credencial. No hace falta: la imagen es pública |
| **ACR con Managed Identity** en Azure | ~USD 5/mes | Es el estándar con imágenes privadas. Descartado sólo por costo; es el camino si el repositorio pasa a privado |
| Token de una GitHub App (dura 1 h), renovado por un job | USD 0 | Complejidad (clave de la App, job que la renueve) sin ningún beneficio sobre una imagen pública |
| Imagen pública sin credenciales **en las dos nubes** | USD 0 | Válido, pero deja a GCP dependiendo de GHCR en tiempo de ejecución, cuando el patrón completo ahí no cuesta nada |
| Push desde CI directo a cada registro | ~USD 0 | Dos orígenes del artefacto, en contra del ADR-0008. La promoción por digest mantiene uno solo |

## Consecuencias

**Se gana**:

| | Antes | Después |
|---|---|---|
| Credenciales personales | 2, que vencen y cuyo valor nadie conoce | **0** |
| Secretos de registro en las nubes | 2 | **0** |
| Valores en `shared.secrets.tfvars` | 6 | **5**: `rotate-secrets.sh` vuelve a ser utilizable |
| GCP depende de GHCR para correr | sí (espejo remoto) | no: la imagen ya está en su registro |
| Costo | — | ~USD 0.1/mes como máximo (Artifact Registry da 0.5 GB gratis) |

**Se paga**:

- **Azure depende de que la imagen sea pública.** Si el repositorio pasa a
  privado, Azure necesita ACR con Managed Identity. La guarda de CI lo detecta
  primero.
- **Azure baja de un registro externo** en cada revisión y cada ejecución de
  job: si GHCR no está disponible, esos arranques fallan. Es el mismo riesgo que
  hoy con el PAT.
- **El deploy de GCP suma un paso** (`crane copy`, segundos).

**Si el repositorio fuera privado**, sólo cambia Azure: ACR con una cache rule
hacia GHCR (credencial de máquina guardada una vez) o promoción por digest desde
CI, y Managed Identity con `AcrPull` en la app y los jobs. GCP no cambia: su
promoción ya lee con el `GITHUB_TOKEN`.

## Orden de implementación (para no cortar el servicio)

1. **Rama con todos los cambios**: Terraform de las dos nubes, `deploy-gcp.yml`,
   la guarda en `ci.yml`, y quitar `ghcr_*` del script, la plantilla y los
   runbooks.
2. **Antes del merge**, `terraform apply -target` en GCP, sólo para el
   repositorio nuevo y sus dos permisos (`runtime_pull_images` y
   `deployer_push`). El deploy que dispara el merge necesita que existan. El
   permiso de lectura tiene un nombre nuevo a propósito: reutilizar
   `runtime_pull` habría quitado el acceso al espejo viejo mientras Cloud Run
   todavía bajaba de ahí.
3. **Merge**: el deploy de GCP promueve la imagen y apunta Cloud Run al
   repositorio nuevo. Azure todavía usa el PAT.
4. **`rotate-secrets.sh plan`** con los 5 valores, revisado a mano: en Azure se
   quitan los bloques `registry` y el secreto; en GCP se eliminan el espejo, el
   secreto y el permiso. Los otros 5 secretos no cambian. Después, `apply`.
5. **Verificación**: un deploy completo en las dos nubes; el digest en Artifact
   Registry igual al de GHCR; migrate y seed corren; `/health` y un escenario
   funcionan.
6. **Se revocan los dos PAT** en GitHub y se relanza un deploy para probar que
   nada depende de ellos.
