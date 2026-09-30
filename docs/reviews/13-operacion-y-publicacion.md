# Repaso — Etapa "Operación en producción y preparación para publicar"
**Sistema Multi-Agente de Detección de Fraude · handoff de continuidad**

> Documento de cierre de etapa. Condensa lo que pasó entre el cierre de la
> etapa 12 (07/09) y la preparación de la demo para abrirla al público
> (30/09): PR #30 a #65.
>
> Predecesor: `12-gcp-multicloud.md`.
> Decisiones de fondo: ADR-0023 a ADR-0028. Incidentes: 0001 a 0010.
> Contrato: pasa de v0.14 a **v0.15** ([CHANGELOG](../CHANGELOG.md)).

---

## 1. Qué se cerró en esta etapa

Dos semanas del sistema **corriendo de verdad** en Azure y GCP, con sus
incidentes, y después el trabajo para que aguante visitas públicas sin
romperse ni vaciar los créditos.

| Pieza | Archivo | PR | Verificado |
|---|---|---|---|
| Un solo archivo de secretos para las dos nubes | `infra/rotate-secrets.sh`, ADR-0023 | #34 | usado en la migración a Neon nuevo |
| Observabilidad de infra: OTel + Grafana local, `GET /metrics` | `observability/`, ADR-0024 | #41 | stack local levantado |
| Desglose de costo y latencia por nodo en LangSmith | `api/routers/metrics.py`, acta `langsmith-observabilidad.md` | #36, #37 | tarjeta del dashboard |
| Dashboard responsive y pulido mobile; grafo en vivo sin parpadeo | `dashboard/src/` | #50, #52, #53 | 0 cuadros ocultos grabando a 2x |
| Techo de uso de la demo (40/h, 200/día; 20 resoluciones/h) y Swagger apagado en producción | `api/limites_demo.py`, `api/app.py`, ADR-0025 | #57 | Swagger ausente en las dos nubes; `429` probado en tests |
| Cooldown por escenario alineado entre API y dashboard (5 min), con test que los ata | `api/routers/cases.py`, `Transactions.tsx` | #58, #65 | `429` "Probá de nuevo en 5 minutos" en Azure |
| Clientes de proveedores creados una sola vez, bajo lock | `retrieval/embeddings.py`, `arbiter/judge.py`, `explain/narrator.py`, `intel/searcher.py` | #59 | 9 análisis en paralelo en GCP en frío, 0 degradados |
| Escenarios en vivo que cumplen su etiqueta | `scripts/seed_diverse_scenarios.py` | #59 | t1155 → FP-08; t1026 → FP-02 |
| Deploys en fila y sin pisarse | `.github/workflows/deploy-*.yml` | #60 | primer deploy: `ahead`; rerun: `identical` |
| fetch-intel en Haiku, sin prosa, semanal; cada llamada declara su modelo | `intel/`, `explain/narrator.py`, ADR-0026 | #61, #62 | ~USD 0.28 por ejecución (antes ~1.17) |
| Readiness de Azure en `/health`; `/ready` sin caché | `api/app.py`, `infra/azure/main.tf`, ADR-0027 | #63 | 0 llamadas periódicas a `/ready` en los logs |
| Imagen sin tokens personales: promoción por digest en GCP, imagen pública en Azure, guarda en CI | `infra/`, `deploy-gcp.yml`, `ci.yml`, ADR-0028 | #64 | deploys después de revocar los dos PAT |
| Base en un proyecto nuevo de Neon, armada desde cero | migrate + seed + `seed_showcase.py` | — | gate 7000/7000 contra la base nueva |

---

## 2. Lo jugoso: diez incidentes

Ningún incidente lo detectó una alerta. Todos salieron de mirar: la consola
de un proveedor, los logs, una prueba de carga o el uso de la demo.

**Costo**

| # | Qué pasó | Causa | Aprendizaje |
|---|---|---|---|
| 0001 | fetch-intel quemaba crédito de Anthropic sin guardar nada | sesión de base abierta durante 7–10 min de búsquedas (Neon la cerraba) y un reintento automático que duplicaba el gasto | un job que llama a un proveedor pago no reintenta solo |
| 0004 | Sonnet 4.6 costaba ~22x más que el resto | `MAX_USES=3` en la búsqueda web | una herramienta del proveedor cobra cada ronda |
| 0005 | Neon despierto todo el día | readiness probe cada 10 s con `SELECT 1` | todo lo periódico cuesta en una base serverless |
| 0010 | fetch-intel ~USD 1.1/día sin efecto en la demo | la prosa del modelo se pagaba y se tiraba, y los resultados volvían como entrada | pedir que no redacte y ponerle tope; medir antes de optimizar |

**Datos**

| # | Qué pasó | Causa | Aprendizaje |
|---|---|---|---|
| 0003 | 10 decisiones `ESCALATE_TO_HUMAN` falsas en la base | los outages de 0001/0002 degradaron el árbitro al piso | un outage deja rastro en los datos; hay que limpiarlo con respaldo |
| 0006 | el dashboard sondeaba cada 3 s casos borrados | IDs en `localStorage` que la limpieza de 0003 no miró | revisar las referencias fuera de la base antes de borrar |
| 0008 | "Comercio con historial de fraude" aprobaba | el sufijo por corrida anulaba la identidad del comercio | una transformación verificada en unos casos no se hereda a los que se suman |

**Concurrencia y despliegue**

| # | Qué pasó | Causa | Aprendizaje |
|---|---|---|---|
| 0002 | GCP con claves viejas | se rotó sólo en Azure | un secreto compartido se rota desde un solo lugar (ADR-0023) |
| 0007 | RAG degradado en el primer pico después de un arranque en frío | varios hilos creaban el cliente perezoso y el recolector cerraba los huérfanos en vuelo | lo perezoso compartido entre hilos necesita lock |
| 0009 | las dos nubes quedaron en la imagen vieja | dos deploys en paralelo; el último en terminar ganaba | "workflow en verde" no es "versión correcta": se verifica el tag que corre |

---

## 3. Decisiones de fondo

| ADR | Decisión | Por qué |
|---|---|---|
| [0023](../adr/0023-un-solo-archivo-de-secretos-compartido-entre-azure-y-gcp.md) | un archivo de secretos y un script para las dos nubes | rotar en dos lugares a mano falló (0002) |
| [0024](../adr/0024-observabilidad-de-infra-con-opentelemetry-y-stack-grafana.md) | OTel + stack Grafana local; `/metrics` Prometheus | observabilidad de infra sin costo en la nube |
| [0025](../adr/0025-la-demo-publica-se-protege-del-abuso-sin-autenticacion.md) | techo de uso contado en la base, sólo en producción; sin Swagger | la API es pública y sin auth: el gasto no tenía techo |
| [0026](../adr/0026-cada-llamada-a-un-llm-usa-el-modelo-mas-chico-que-alcanza.md) | cada llamada usa el modelo más chico que alcanza y lo declara; la explicación volvió a Sonnet | el costo era fetch-intel; Haiku omitía los motivos en la explicación |
| [0027](../adr/0027-el-readiness-de-azure-responde-por-el-proceso-no-por-neon.md) | el readiness responde por el proceso, no por Neon | costo base ~0 y sin cortes de 30 s |
| [0028](../adr/0028-sin-credenciales-personales-en-el-camino-de-la-imagen.md) | cero credenciales personales; promoción por digest en GCP | los PAT vencían, nadie tenía su valor y bloqueaban la rotación |

---

## 4. Convenciones nuevas fijadas

- **Merge commit, no squash** (`CLAUDE.md`): la rama queda visible y los hashes
  que citan los incidentes siguen existiendo.
- **"Antes de cerrar un cambio"** (`CLAUDE.md`, nacido del 0006): referencias
  fuera de la base, estado que sobrevive, caminos de error, costo de lo
  periódico y verificación después del deploy.
- **Un workflow en verde no prueba la versión**: después de cada deploy se lee
  el tag que corre cada nube (0009).
- **Un probe periódico nunca toca una dependencia compartida** (ADR-0027).
- **Cada llamada a un LLM declara su modelo**, y un test ata el modelo que viaja
  al que se sella (ADR-0026).
- **Ninguna credencial personal en producción** (ADR-0028).
- **Una prueba contra un proveedor real se dimensiona contra su cuota**: la
  reproducción del 0007 agotó un minuto de la cuota de Gemini.
- **Un secreto nunca se imprime para compararlo**: se compara por hash (así se
  detectó la `DATABASE_URL` equivocada antes de aplicarla).

### Footguns verificados en esta etapa

| Trampa | Detalle |
|---|---|
| `Client.__del__` de los SDK | google-genai y anthropic cierran su cliente HTTP al recolectarse; un cliente pisado en una carrera se cierra con un request en vuelo (0007) |
| `workflow_run` sin `concurrency` | dos merges seguidos: el deploy viejo puede terminar último (0009) |
| `az rest` PATCH con el JSON de la CLI | la CLI exporta campos de preview (`imageType`) que la API rechaza; leer y escribir con la misma `api-version` |
| `postgresql://` en `DATABASE_URL` | SQLAlchemy busca `psycopg2` (no instalado); tiene que ser `postgresql+psycopg://` |
| Neon autoscaling hasta 2 CU | una prueba de carga escala y gasta 8x por hora; para esta base alcanza 0.25 fijo |

---

## 5. Hallazgos y deuda

- **Corpus de inteligencia externa casi vacío:** la búsqueda devuelve fuentes
  sin fecha y el script las descarta (0010). FP-10 igual no aplica a la demo
  (fechas fijas de diciembre 2025).
- **El cooldown por escenario vive en memoria de cada nube:** se puede correr el
  mismo escenario una vez en Azure y otra en GCP dentro de los 5 minutos. El
  techo global, contado en la base, cubre el costo.
- **Azure depende de que la imagen sea pública** (ADR-0028). CI lo verifica; el
  camino con imagen privada es ACR con Managed Identity (~USD 5/mes).
- **Sin alertas**: 4xx por endpoint, consumo de Neon, agentes degradados. Sigue
  pendiente, consolidado en el 0006.
- **Tags de contrato faltantes:** `contrato-v0.12` a `v0.14` nunca se crearon.
  Desde `v0.15` se retoma.
- **El proyecto viejo de Neon** queda unos días como respaldo; después se borra.
- Deuda heredada sin cambios: sin autenticación en la API (acta 09 §6.1) y el
  retry propio en `internal_policy_rag` (acta 11 §6.2).

---

## 6. Mapa de archivos al cierre

```
src/multiagent_fraud_detection/
├── api/limites_demo.py                  # techo de uso (ADR-0025)
├── api/app.py                           # sin Swagger en producción; /ready sin caché
├── api/routers/cases.py                 # techo + cooldown de 5 min
├── explain/narrator.py                  # narrate(model=, max_tokens=) por llamada
└── intel/{snapshot,searcher}.py         # Haiku, sin prosa, GENERATION 2

infra/
├── azure/main.tf                        # readiness /health; sin bloque registry
├── gcp/main.tf                          # repo `images` + IAM; sin espejo ni token
└── rotate-secrets.sh                    # 5 valores compartidos

.github/workflows/
├── ci.yml                               # + pull anónimo de la imagen
├── deploy-azure.yml                     # concurrency + guarda `vigente`
└── deploy-gcp.yml                       # + promoción por digest con crane

docs/
├── adr/0023…0028
├── incidentes/0001…0010
└── reviews/13-operacion-y-publicacion.md   # este archivo
```

---

## 7. Qué sigue

1. **Mejoras visuales del dashboard.** Si cambian el grafo en vivo, se vuelven a
   grabar el GIF del README y el video.
2. **Publicación en LinkedIn.**
3. **Primera semana después de publicar:** consumo de Neon a las 24 h, 48 h y
   7 días; gasto diario de Anthropic; logs de 5xx, 429 y agentes degradados en
   las dos nubes; cuota de LangSmith.

---

## 8. Documentación asociada

- ADR-0023 a ADR-0028 (tabla de §3) y los incidentes en [`docs/incidentes/`](../incidentes/)
- [`CHANGELOG.md`](../CHANGELOG.md) — contrato v0.15
- [`langsmith-observabilidad.md`](langsmith-observabilidad.md) y
  [`cd-tiempos-azure-vs-gcp.md`](cd-tiempos-azure-vs-gcp.md) — análisis de esta etapa
- `12-gcp-multicloud.md` — etapa anterior
- Demo principal (Azure): https://ca-fraud-detection-api.graywave-cc1ab2d2.eastus2.azurecontainerapps.io
- Demo de aprendizaje (GCP): https://fraud-detection-api-im2rcartea-uc.a.run.app
