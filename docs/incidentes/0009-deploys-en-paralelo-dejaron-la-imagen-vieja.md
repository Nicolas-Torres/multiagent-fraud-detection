# Incidente 0009 — dos deploys en paralelo dejaron las nubes en la imagen vieja

**Fecha**: 2026-09-26. **Detectado**: al verificar después del merge de los PR
#58 y #59, comparando la imagen que corría cada nube con el último commit de
`main`. No hubo alerta del sistema.
**Impacto**: durante unos 15 minutos, Azure y GCP sirvieron `sha-5b47f89`, sin
los arreglos de los incidentes 0007 y 0008 que ya estaban en `main`. Los
workflows terminaron en verde, salvo uno de Azure que falló.

## Síntoma

- Dos merges seguidos (#58 y #59, con merge commit) dispararon dos CI y, por
  cada uno, un deploy a cada nube. Los cuatro deploys arrancaron en el mismo
  segundo (06:21:07 UTC).
- En Azure, uno falló en la migración:
  `ContainerAppsJobOperationInProgress: Cannot modify a container apps job
  'caj-fraud-detection-migrate' because there is an active provisioning operation
  in progress`.
- Al terminar, las dos nubes corrían `sha-5b47f89` (el merge de #58), no
  `sha-904b426` (el de #59, el último de `main`).

## Causa raíz

Los workflows de deploy (`workflow_run` sobre CI) no tenían `concurrency`.
Dos deploys corrían en paralelo, y el que terminaba último fijaba la imagen,
aunque fuera el commit más viejo. Con squash merge era menos probable (un PR
por vez), pero no imposible. El merge commit, adoptado el mismo día, lo volvió
esperable: cada PR dispara su propio CI.

## Fix

En `deploy-azure.yml` y `deploy-gcp.yml`:

- `concurrency` por workflow, sin cancelar el que está en curso: los deploys a
  una nube corren de a uno.
- Un paso `vigente`, después del login, lee el commit que corre la nube y lo
  compara con el del run (`gh api compare`). Si la nube ya corre un
  descendiente (`behind`), el run no toca nada. Ante cualquier otra respuesta,
  o un error, despliega como antes.

**Por qué no se compara contra `main`:** CI ignora los pushes que sólo tocan
docs. Si `main` avanza con un commit de docs mientras corre el CI de un commit
de código, comparar contra `main` saltaría el deploy del código, y el de docs
nunca deploya.

**Consecuencia:** un rollback ya no se puede hacer relanzando el deploy de un
commit viejo (se saltaría). Se hace apuntando la app a la imagen anterior a
mano, como en `docs/runbook_azure_setup.md`.

Remediación inmediata: se relanzó el CI de `904b426`, y las dos nubes quedaron
en `sha-904b426`.

## Verificación

- `gh api compare` contra los commits reales del incidente: nube en `904b426` y
  run de `5b47f89` da `behind` (se salta); al revés da `ahead` (despliega); el
  mismo commit da `identical` (despliega); un commit inexistente da error
  (despliega).
- **Pendiente**: el primer deploy real con el workflow nuevo.

## Aprendizaje

Un cambio de proceso (squash → merge commit) también cambia la carga sobre el
pipeline. Y "terminó en verde" no es "quedó la versión correcta": después de
cada deploy se verifica el tag que corre la nube, no el estado del workflow.
