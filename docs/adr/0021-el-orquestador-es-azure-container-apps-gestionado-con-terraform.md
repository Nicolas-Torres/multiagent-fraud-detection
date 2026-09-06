# ADR-0021: el orquestador de despliegue es Azure Container Apps, gestionado con Terraform

- **Estado**: aceptado
- **Fecha**: 2026-09-06

## Contexto

El contrato (§1) y los ADR-0008/0009/0010 fijaron el diseño de CI/CD
**asumiendo un reparto de dos personas**: yo construyo y publico la imagen en
GHCR (CI), mi compañero la despliega (CD) sobre "un orquestador, a su
criterio". Las secciones de Consecuencias de ADR-0008 y ADR-0009 ilustran ese
criterio con vocabulario de Kubernetes (`kubectl`, labels de pod,
`activeDeadlineSeconds`, `backoffLimit`) porque, en ese momento, era la
suposición razonable para un CD ajeno.

Ese reparto ya no existe: CI, CD, imagen y despliegue quedan enteramente en
mis manos. Y a diferencia de cuando se escribieron esos ADR, hoy **no hay
ninguna infraestructura real** —ni AWS, ni Azure, ni GCP, ni un clúster de
Kubernetes— así que el orquestador queda genuinamente abierto por primera
vez, no heredado de una decisión anterior.

Tres restricciones nuevas, propias de que esto es una pieza de portafolio que
mantengo solo:

- **Debe estar funcional 24/7.** Un visitante (potencialmente quien evalúa
  una postulación) no debería encontrarlo dormido ni con un cold-start
  perceptible.
- **Costo moderado y aceptable, no gratis a toda costa** — es un gasto que
  se justifica por el retorno esperado, pero sigue siendo dinero que sale de
  mi bolsillo mes a mes, indefinidamente.
- **Cero tiempo de administración de sistema operativo.** No hay un
  compañero de CD ni un equipo de plataforma detrás; cualquier parche de SO
  o de nodo lo aplico yo mismo, a costa del tiempo que necesito para el resto
  del proyecto (el informe, las referencias, el video de exposición siguen
  pendientes).

El enunciado del reto (`docs/requisitos/reto_de_aplicacion.md`) pide
"despliegue en la nube (preferentemente Azure, se acepta AWS)". La rúbrica
(`docs/requisitos/rubrica.md`) pide, para el nivel más alto, un "pipeline
CI/CD operativo, despliegue exitoso en nube **o** Kubernetes con evidencia"
—las presenta como alternativas, no como requisito conjunto—.

## Decisión

El orquestador es **Azure Container Apps**, declarado con **Terraform**
(`azurerm`, estado remoto en Azure Storage desde el primer commit, nunca
estado local).

Los cuatro modos de arranque de la imagen (contrato §1.2) se mapean así:

| Modo | Recurso de Azure |
|---|---|
| Servir (`uvicorn`) | Container App, `min-replicas: 1` — nunca en cero, para que no haya cold-start visible |
| Migrar (`alembic upgrade head`) | Container Apps Job, disparo manual desde el pipeline de CD |
| Sembrar (`seed.py`) | Container Apps Job, disparo manual desde el pipeline de CD, después del de migrar |
| Fetch-intel | Container Apps Job, disparo programado (cron) |

La base de datos queda fuera de este ADR — se resuelve por separado que sea
un proveedor neutral a la nube (no un servicio nativo de Azure), precisamente
para que agregar un segundo proveedor de cómputo más adelante no obligue a
replicar datos entre nubes.

**GCP queda explícitamente fuera del alcance de este ADR.** Es un objetivo
de aprendizaje declarado, secuenciado después de que Azure funcione de punta
a punta con evidencia — se decide y se documenta en un ADR propio cuando
llegue esa fase, no acá.

**Autenticación de GitHub Actions hacia Azure: OIDC, no un secret estático.**
El workflow usa `azure/login` con *federated credentials* (un App
Registration de Azure AD configurado para confiar en el emisor OIDC de
GitHub, acotado a este repo) — GitHub Actions obtiene un token de corta vida
en cada corrida, nunca hay una clave de larga vida guardada como secret del
repositorio. Se descarta un Service Principal con secret estático por el
motivo usual: una clave que no expira y que vive en la configuración de
GitHub es una superficie de robo permanente; con OIDC no hay clave que robar
—el token vale sólo para esa corrida—.

**Estado de Terraform: remoto desde el primer commit, nunca local.** Un
Storage Account + contenedor blob dedicados a Terraform, creados una sola
vez, a mano (`az cli` o el portal) — es la única pieza de infraestructura
que no gestiona el propio Terraform, porque el backend remoto tiene que
existir *antes* de que haya un Terraform que gestione nada. Todo lo demás
(Container Apps, Jobs, secrets) sí es Terraform desde el día uno. Estado
local se descarta de entrada: vive en la máquina de una sola persona, no
sobrevive un cambio de laptop, y no hay forma de que el pipeline de CI lo
lea para hacer `plan`/`apply`.

## Alternativas descartadas

**Kubernetes (AKS/EKS/GKE).** Es lo que ADR-0008/0009 ejemplificaban
implícitamente, y es la opción que más se parece a "orquestación real" en el
papel. Se descarta como orquestador principal porque el control plane
administrado tiene un piso de costo fijo mensual —del orden de varias
decenas de dólares sólo por el clúster, antes de sumar nodos— y una
superficie operativa real (node pools o perfiles serverless, RBAC, un
ingress controller) que un solo desarrollador sostiene indefinidamente para
un proyecto que no lo necesita: la rúbrica ya acepta "nube" como alternativa
a "Kubernetes", no como un peldaño inferior.

**AWS (ECS Fargate o App Runner).** Aceptado por el enunciado, no preferido.
Además, a diferencia de Azure Container Apps Jobs, ECS Fargate no tiene un
primitivo "Job" tan directo — el mismo comportamiento (abortar o no abortar,
una sola instancia) se arma con Task Definitions y `run-task`, más piezas
para el mismo resultado.

**Una sola VM con `docker compose`.** La opción más barata y la más parecida
a correr el proyecto tal cual está en local — de hecho, es la que se usaría
como red de contención si Container Apps resultara inviable en la práctica.
Se descarta como target principal porque no demuestra ninguna orquestación
real, deja el parcheo del sistema operativo enteramente en mis manos, y
encaja peor con "pipeline operativo... con evidencia": una VM con SSH es más
difícil de presentar como evidencia de CI/CD que un despliegue declarado en
Terraform.

**Azure Kubernetes Service (AKS), ya que de todos modos se prefiere Azure.**
Mismo argumento que Kubernetes en general: el control plane de AKS no cobra
aparte (a diferencia de EKS), pero los node pools sí, y siguen exigiendo el
mismo nivel de operación (parches de SO de los nodos, upgrades de versión de
Kubernetes) que Container Apps evita por completo al ser serverless.

## Consecuencias

**Se gana** un despliegue serverless que no exige administrar un sistema
operativo ni un clúster; un primitivo de Job nativo (Azure Container Apps
Jobs) que resuelve exactamente la semántica que ADR-0009/0010 ya diseñaron
—abortar o no abortar, una sola instancia, disparo programado para
fetch-intel— sin tener que operar Kubernetes para conseguirlo; y una ruta de
aprendizaje hacia GCP que no compite por tiempo con el entregable principal,
porque queda fuera del alcance de este ADR hasta que le toque su propia
fase.

**Se paga:**

- **Los ejemplos concretos de ADR-0008 y ADR-0009 quedan desactualizados.**
  `kubectl`/labels de pod (ADR-0008) y `activeDeadlineSeconds`/
  `backoffLimit` (ADR-0009) eran ilustraciones de Kubernetes, no la
  decisión en sí — se les agrega una nota señalando el orquestador real
  (Azure Container Apps Jobs usa `replicaTimeout` y `replicaRetryLimit`
  para el mismo propósito), sin tocar la Decisión ni las Alternativas
  descartadas de ninguno de los dos: el hand-off por digest y la semántica
  de Job siguen siendo válidas tal cual están escritas.
- **Container Apps es unívocamente de Azure.** Si más adelante conviene
  migrar de nube por completo —no sólo agregar GCP como segundo target de
  aprendizaje—, el Terraform de cómputo no es reusable; sólo el Dockerfile y
  el pipeline de CI hasta el paso de build sí lo son.
- **Un solo proveedor de cómputo primario concentra el riesgo de
  disponibilidad** del portafolio en esa cuenta y esa suscripción —mitigado
  parcialmente porque la base de datos vive fuera de Azure: una caída de
  Azure no se lleva los datos con ella.
- **`min-replicas: 1` es un costo fijo, elegido a propósito.** Es la
  diferencia entre "barato" y "gratis": se paga para que nadie encuentre el
  sistema dormido, en línea con la restricción de 24/7 de este mismo
  contexto.
