# Repaso — Etapa "CI/CD y despliegue en Azure"
**Sistema Multi-Agente de Detección de Fraude · handoff de continuidad**

> Documento de cierre de etapa. Destila lo decidido y construido en las
> ramas `feature/ci-cd-*` y `docs/runbook-*`, para retomar en el chat
> siguiente con el contexto ya condensado.
>
> Predecesor: `10-dashboard.md`.
> Decisión de fondo: [ADR-0021](../adr/0021-el-orquestador-es-azure-container-apps-gestionado-con-terraform.md).
> Bitácora comando-por-comando, completa: [`docs/runbook_azure_setup.md`](../runbook_azure_setup.md)
> — este acta resume el porqué y lo jugoso; esa bitácora tiene el cómo
> exacto, para reproducirlo o auditarlo.

---

## 1. Qué se cerró en esta etapa

CI/CD completo y una infraestructura real, en producción, pagada por
el usuario — no una maqueta. El proyecto entero "es mío y yo lo cubro
todo" (decisión explícita del usuario): esta etapa cubre esa promesa
de punta a punta.

| Pieza | Archivo | Verificado |
|---|---|---|
| ADR de la arquitectura de despliegue, con alternativas descartadas | `adr/0021-*.md` | discutido en modo plan, con el usuario, antes de tocar código |
| Lint del backend (ruff), adoptado por primera vez | `pyproject.toml`, 55+ archivos | `ruff check .` limpio, gate nuevo en CI |
| CI: test (Postgres efímero) → build → push a GHCR | `.github/workflows/ci.yml` | corridas reales en PR y en `main` |
| `paths-ignore` + cache de capas Docker (`type=gha`) | `ci.yml` | evaluado contra un workflow de referencia de otro proyecto |
| Módulo Terraform: Environment, Container App, 3 Jobs | `infra/azure/*.tf` | `terraform plan`/`apply` reales, 6/6 recursos creados |
| Backend remoto de Terraform (Storage Account) | bootstrap manual, `infra/azure/backend.tf` | `terraform init` contra el backend real |
| Identidad OIDC para GitHub Actions (sin secreto estático) | App Registration + federated credential | login real desde CI, confirmado |
| CD: migrar → servir → sembrar → fetch-intel | `.github/workflows/deploy-azure.yml` | **corrida real de punta a punta**, cero pasos manuales |
| Infraestructura real, 24/7, con Neon (Postgres+pgvector) | Azure Container Apps, `rg-fraud-detection` | `/health`/`/ready` en 200, casos reales corriendo |

---

## 2. Lo jugoso: tres bugs reales, tres formas distintas de encontrarlos

### 2.1 Un secret vacío que Azure rechaza — encontrado por un `apply` real

`LANGSMITH_API_KEY` es opcional por diseño (ADR-0013: sin clave, el
sistema traza igual sin trazar). El primer `terraform apply` real creó
2 de 6 recursos y se cayó en los otros 4: Azure Container Apps
rechaza declarar un `secret` con `value = ""` — exige un valor real o
una referencia a Key Vault. `main.tf` armaba ese secret igual,
incondicionalmente. Ni `terraform validate` ni `terraform plan` lo
detectan —ambos son client-side o de solo lectura—, hizo falta el
`apply` real contra la API de Azure para que apareciera. Se corrigió
con un `concat()` condicional: el par secret/env de LangSmith sólo se
arma si `var.langsmith_api_key != ""`.

**Lección**: `validate` y `plan` no sustituyen un `apply` real contra
un recurso nuevo — algunas reglas del proveedor sólo se conocen
cuando de verdad intenta crear el recurso.

### 2.2 La vitrina rota en producción — encontrado por el usuario, navegando

El panel de vitrina por defecto (`Transactions.tsx`) usa 5 `case_id`
**horneados en el build del frontend**
(`dashboard/src/data/showcase_cases.json`), escritos por
`scripts/seed_showcase.py` corriendo el grafo real contra Postgres
**local**. La imagen que Fase 3 desplegó nunca corrió ese script
contra Neon — los IDs no existían ahí. `caj-fraud-detection-seed`
(`scripts/seed.py`) no alcanza: ese script deliberadamente no crea
casos, sólo historial.

Arreglado a mano esta vez: `seed_showcase.py` corrido en local apuntando
a Neon (gasta LLM real), commit del JSON regenerado, rebuild + push +
`az containerapp update --image`. **Deuda declarada, no resuelta**: el
próximo deploy real va a volver a romper la vitrina, porque
`seed_showcase.py` todavía no es parte del pipeline de CD — sigue
siendo un paso manual (§6.1).

### 2.3 Un 429 de Gemini en una corrida en vivo — encontrado por el usuario, con `@degrades` funcionando

`internal_policy_rag` degradó con "Evidencia incompleta" en una
transacción real. Diagnóstico completo por Log Analytics
(`ContainerAppConsoleLogs_CL`), sin adivinar: `429 RESOURCE_EXHAUSTED`
del proveedor de embeddings. Se descartaron dos hipótesis con datos
reales antes de aceptar la tercera: el índice vectorial estaba
completo (`policy_chunks`: 11/11, todos con embedding), y la cuota real
en Google Cloud Console mostraba apenas 12/3000 RPM de uso — nada
agotado. Conclusión: un límite de ráfaga por segundo, no documentado
en el panel de cuota agregada, contra el que el retry interno del SDK
`google-genai` (basado en `tenacity`, fuera de nuestro control) no
alcanzó a proteger en ese caso puntual.

Esto **no es un bug** — es `@degrades` (regla del proyecto) haciendo
exactamente lo que tiene que hacer: degradar con un mensaje honesto en
vez de inventar una señal de fraude que no analizó. Mejora anotada, no
implementada: envolver la llamada a `embedder.embed()` con un retry
propio, de backoff más largo que el del SDK (tarea pendiente #45).

---

## 3. El error de diagnóstico que valió la pena corregir

El role assignment de la identidad OIDC (`github-oidc-fraud-detection`
→ `Contributor` sobre `rg-fraud-detection`) falló durante gran parte
de la etapa con `MissingSubscription`, incluso en una simple lectura.
El diagnóstico de ese momento —demora de propagación del subsistema de
RBAC en una suscripción Pay-As-You-Go recién activada— sonaba
razonable con la evidencia disponible, y **estaba mal**.

Se resolvió por el Portal (sin problema) y se confirmó la causa real
aislando la variable correcta: `az role assignment list` **sin**
`--assignee` funcionaba de inmediato y mostraba la asignación —que ya
existía—; **con** `--assignee` seguía fallando incluso con una sesión
de `az login` recién refrescada. El problema nunca fue la suscripción:
era ese flag puntual resolviendo contra Microsoft Graph en esta sesión
del CLI.

**Lección, otra vez**: cuando la explicación más razonable a primera
vista no se puede verificar directamente, aislar variable por variable
gana más rápido que seguir reintentando la misma hipótesis.

---

## 4. Decisiones de fondo y su porqué

### 4.1 Terraform con estado remoto, nunca local (ADR-0021)

El backend (`azurerm`, Storage Account) se bootstrapea a mano, una
sola vez, porque tiene que existir *antes* de que haya un Terraform
que lo use. Estado local no sobrevive un cambio de máquina y el propio
CD (que corre en un runner efímero) no podría leerlo.

### 4.2 OIDC, nunca un secreto estático

La identidad de GitHub Actions se autentica con un token de vida
cortísima por corrida (federated credential, acotada a
`repo:.../ref:refs/heads/main`), nunca con una clave guardada en
GitHub que no expira. Costó más de armar (App Registration + SP +
federated credential + role assignment) que un secret plano, pero
elimina una clase entera de riesgo (una clave filtrada no sirve para
nada fuera de esa corrida puntual).

### 4.3 `sha-<7>` siempre, nunca `latest` (ADR-0008, reafirmado)

El CD calcula el tag a deployar desde
`github.event.workflow_run.head_sha`, no reconstruye la imagen — la
misma que CI ya validó y publicó es la que se despliega, sin
divergencia posible entre "lo que se testeó" y "lo que corre".

### 4.4 Migrar aborta el deploy si falla (ADR-0009, llevado a CD real)

`deploy-azure.yml` actualiza y corre el Job de migrar primero, sondea
su estado, y si no sale `Succeeded` corta el workflow ahí —la
Container App que sirve nunca se toca. Sembrar corre después, con
`continue-on-error: true`: no bloqueante, porque es idempotente
(ADR-0010).

### 4.5 Costo moderado, con fecha de revisión

Azure Container Apps con `min_replicas=1` (nunca en cero, sin
cold-start) más Neon en su free tier: del orden de una decena de
dólares al mes. El usuario lo aceptó explícitamente como una prueba de
~1 mes, con intención declarada de revisar una opción más barata
después — no es una decisión de infraestructura cerrada para siempre.

---

## 5. Convenciones nuevas fijadas

- **Un `--assignee`/filtro que falla no prueba que el recurso de fondo
  esté mal** — aislar el flag antes de aceptar la explicación más
  "razonable" a primera vista (§3).
- **Los Container Apps Jobs cargan su imagen por separado de la app
  que sirve** (`az containerapp job update --image`, distinto de
  `az containerapp update --image`) — un CD tiene que actualizar los
  cuatro recursos de cómputo, no sólo uno.
- **Un JSON horneado en el build que referencia IDs de una base
  externa es una dependencia oculta entre el build y el seed** — el
  próximo trabajo en esta área tiene que resolver esto de raíz (§6.1),
  no repetir el parche manual.
- **`terraform plan`/`validate` no sustituyen un `apply` real** contra
  un proveedor nuevo — algunas validaciones sólo existen en su API
  (§2.1).

### Footguns verificados en esta etapa

| Trampa | Detalle |
|---|---|
| Secret vacío en Azure Container Apps | `value = ""` en un bloque `secret` es rechazado (`ContainerAppSecretInvalid`) — un secret opcional tiene que omitirse por completo, no declararse vacío. §2.1 |
| `az role assignment ... --assignee` | Puede fallar (`MissingSubscription`) por una resolución de Microsoft Graph rota en la sesión del CLI, sin que el recurso de fondo tenga ningún problema — aislar sacando el flag. §3 |
| `-out=/dev/null` en Git Bash sobre Windows | Se traduce a un archivo literal `nul`, no al dispositivo nulo real — inofensivo acá porque Windows trata `nul` como reservado (no crea un archivo real), pero no asumir que `/dev/null` es portable en este entorno |
| JSON horneado en el build del frontend, IDs de una base externa | Cualquier dato que un script de seed escriba a un archivo del repo (no a la base) es una dependencia oculta entre "cuándo se corrió el seed" y "contra qué imagen" — se rompe con total naturalidad en el primer deploy contra una base distinta. §2.2 |
| Cuota agregada (RPM/TPM/RPD) no es el único límite | Un proveedor puede tener un límite de ráfaga por segundo sin publicarlo en el panel de cuota mensual/por-minuto — un 429 con cuota de sobra no prueba que no sea rate limiting. §2.3 |

---

## 6. Hallazgos y deuda

### 6.1 La vitrina depende de un paso manual posterior al build (abierto)

`seed_showcase.py` escribe `dashboard/src/data/showcase_cases.json`
corriendo contra la base que tenga a mano en ese momento — hoy eso es
"lo que sea que tenga el desarrollador en su máquina cuando lo corre a
mano". El próximo deploy real (cualquier push a `main` con cambios de
código) va a reconstruir la imagen sin ese paso y romper la vitrina de
nuevo, hasta que alguien la vuelva a correr a mano contra Neon. Se
necesita resolverlo de raíz —probablemente corriendo
`seed_showcase.py` como parte del propio pipeline de CD, después de
`caj-fraud-detection-seed`, antes de servir— antes de considerar esta
etapa completamente cerrada para un uso real y recurrente.

### 6.2 Retry propio pendiente en `internal_policy_rag` (tarea #45)

Ver §2.3. Anotado, no implementado — el usuario prefirió seguir
avanzando y dejarlo como mejora futura.

### 6.3 Fase 6 (GCP), explícitamente diferida

El usuario pidió multinube "a modo de aprendizaje", con Terraform
elegido en parte por eso — pero secuenciado después de que esta etapa
esté completamente cerrada, no en paralelo. No empezada.

### 6.4 Sin autenticación en los endpoints públicos del demo (heredado, sigue igual)

Mismo criterio que las etapas anteriores (actas 09 §6.1, 10 §6.1): la
rúbrica no la exige, y el cooldown en memoria ya cubre el riesgo real
(gasto de API).

---

## 7. Mapa de archivos al cierre

```
.github/workflows/
├── ci.yml                              # test (Postgres efímero) -> build -> push a GHCR
└── deploy-azure.yml                    # workflow_run tras CI -> migrar -> servir -> sembrar -> fetch-intel

infra/azure/
├── backend.tf                          # backend remoto (bootstrapeado a mano)
├── providers.tf
├── variables.tf                        # incl. langsmith_api_key con default "" (§2.1)
├── main.tf                             # RG (data), Log Analytics, Environment, Container App, 3 Jobs
├── outputs.tf                          # api_fqdn
└── README.md                           # comandos de bootstrap, resumidos

docs/
├── adr/0021-*.md                       # la decisión de fondo
├── adr/0008-*.md, 0009-*.md, 0010-*.md # notas cortas agregadas, sin romper su inmutabilidad
├── runbook_azure_setup.md              # bitácora completa, comando por comando — la pidió el usuario para su aprendizaje
└── reviews/11-ci-cd-azure.md           # este archivo

pyproject.toml                          # [tool.ruff] — gate nuevo de CI
```

---

## 8. Qué sigue

**Antes de dar esta etapa por completamente cerrada para uso real**:
resolver §6.1 (la vitrina no puede depender de un paso manual).

**Fase 6** (GCP, aprendizaje, explícitamente no bloqueante): un segundo
módulo Terraform apuntando al mismo Neon, con su propio ADR corto
explicando por qué se agrega un segundo proveedor.

**Deuda declarada para el informe**: sin autenticación (§6.4, heredada),
vitrina dependiente de un paso manual (§6.1), retry propio pendiente en
`internal_policy_rag` (§6.2) — las tres explícitas, ninguna es un
olvido.

---

## 9. Documentación asociada

- [ADR-0021](../adr/0021-el-orquestador-es-azure-container-apps-gestionado-con-terraform.md)
- [`docs/runbook_azure_setup.md`](../runbook_azure_setup.md) — la bitácora completa, comando por comando
- `10-dashboard.md` — etapa anterior
- Demo en vivo: https://ca-fraud-detection-api.graywave-cc1ab2d2.eastus2.azurecontainerapps.io
