# Repaso — Etapa "Después de publicar: seguridad, experiencia del visitante y criterio sobre modelos"
**Sistema Multi-Agente de Detección de Fraude · handoff de continuidad**

> Documento de cierre de etapa. Condensa lo que pasó entre el cierre de la
> etapa 13 (30/09) y el 06/10: la última revisión antes de publicar, la
> publicación en LinkedIn (02/10) y lo que se aprendió evaluando modelos:
> PR #67 a #76.
>
> Predecesor: `13-operacion-y-publicacion.md`.
> Decisiones de fondo: ADR-0029 a ADR-0032 y el desvío D-08. Incidentes: 0011 y 0012.
> Contrato: pasa de v0.15 a **v0.16** ([CHANGELOG](../CHANGELOG.md)).
> Evaluaciones: [`docs/evaluaciones/`](../evaluaciones/).

---

## 1. Qué se cerró en esta etapa

Tres frentes: la demo, tal como la ve un visitante; una revisión de seguridad
antes de publicar; y, ya publicada, una serie de pruebas sobre modelos que
terminó corrigiendo el árbitro.

| Pieza | Archivo | PR | Verificado |
|---|---|---|---|
| Casos que un reinicio dejaba en curso se cierran al arrancar | `api/casos_interrumpidos.py` | #67 | 2 casos trabados cerrados en local |
| La aprobación de la vitrina sobrevive al sufijo en vivo: T-1031 reemplaza a T-2579 | `api/showcase.py`, `tests/test_showcase_live.py` | #68 | corrida en vivo de T-1031 en GCP: APPROVE |
| Dashboard: Inicio, etiquetas en español, colores por decisión, grafo fijo, Observability, chips en Arquitectura | `dashboard/src/` | #69 | 18 páginas × 2 nubes, escritorio y móvil, sin errores de consola |
| La ruta del dashboard ya no sirve archivos fuera de `dist/` | `api/app.py`, `tests/test_spa_route.py` | #70 | `/..%2F..%2Fpyproject.toml` devuelve la página en las dos nubes |
| Página 404, el detalle de un caso deja de sondear, vista previa del link, `urllib3` 2.8.0, `shadcn` a desarrollo | `dashboard/`, `uv.lock` | #71 | Playwright en producción; `npm audit --omit=dev`: 0 |
| fetch-intel a demanda; el scheduler de GCP corregido y en pausa | `infra/`, ADR-0029 | #72 | scheduler → `200`, ejecución `exit(0)` |
| Desvío D-08: investigación del caso, no autorización en línea | `docs/trazabilidad.md`, `reviews/tiempo-real-vs-investigacion.md` | #73 | — |
| La espera entre corridas es por visitante | `api/routers/cases.py`, `tests/test_live_repetition.py`, ADR-0030 | #74 | dos corridas seguidas de la misma fila en Azure: `202` y `202` |
| Modo de razonamiento explícito; topes que lo cubren; una respuesta cortada es un error | `arbiter/`, `debate/`, `explain/`, ADR-0031 | #75 | 12 casos difíciles, 0 cortes; LangSmith: `end_turn` en todas |
| Con un agente de señales caído, el piso no es APPROVE | `domain/engine.py` (`piso_efectivo`), ADR-0032 | #76 | estables 9/12 → 11/12; gate 7000/7000 sin cambios |

**Diagramas:** no hubo cambios en la base ni en la topología del grafo, y el C4 no
menciona nada de lo que cambió. `export_data_model_diagram.py --check`, al día.

---

## 2. Incidentes

| # | Qué pasó | Causa | Aprendizaje |
|---|---|---|---|
| 0011 | La aprobación de la vitrina (T-2579) escalaba cada vez que un visitante la re-ejecutaba | El sufijo de la corrida en vivo volvía nuevo al dispositivo; con un país ya extranjero para el cliente, se completaba FP-02 | La condición no es "qué políticas disparan en la fila", sino "la corrida en vivo llega al mismo veredicto". Lo prueba un test con el motor |
| 0012 | La ruta del dashboard servía cualquier archivo del contenedor (`/..%2F..%2F…`) | El catch-all recibe la ruta **decodificada** y la unía a `dist/` sin resolverla | Una ruta que sirve archivos desde un parámetro del cliente es una frontera: se prueba con lo que mandaría un atacante. Sin explotación en los logs de las dos nubes; no hizo falta rotar secretos |

---

## 3. Decisiones de fondo

| ADR | Decisión | Por qué |
|---|---|---|
| 0029 | fetch-intel a demanda en las dos nubes | El snapshot no vence y la demo tiene fechas fijas. Además, el cron de GCP nunca había corrido: host inexistente y token OIDC donde Google pide OAuth |
| 0030 | La espera entre corridas es por visitante, en el navegador | Con la espera global, un visitante recibía `429` por la corrida de otro. Antes de quitarla se probó que repetir una fila 200 veces no cambia su veredicto |
| 0031 | El modo de razonamiento se declara en código, y el tope de tokens lo cubre | Sonnet 5 razona por defecto y ese razonamiento cuenta en `max_tokens`: con 500, un caso difícil cortaba el veredicto del árbitro |
| 0032 | Con un agente de señales caído, el piso sube a CHALLENGE | Con la misma evidencia, el árbitro aprobaba en un caso y pedía verificación en otro. 9 de las 11 políticas dependen de `behavioral_pattern` |
| D-08 | El sistema cubre la investigación del caso, no la autorización en línea | El enunciado pide "tiempo real"; con 4 llamadas a LLM, el análisis tarda 11–22 s. La capa en línea necesitaría el piso de las reglas, que ya está separado |

**Evaluaciones que no cambiaron el modelo:**

- **Jev como árbitro:** confirma el piso igual que Sonnet (98/98), pero omitió
  todas las escaladas (8 de 8). Descartado.
- **Sonnet 5.5:** decide igual, sin ganancia de velocidad ni costo. No se migra
  todavía.

---

## 4. Convenciones nuevas fijadas

- **El modo de razonamiento de cada llamada a un LLM vive en código**, junto a su
  modelo, y viaja explícito (ADR-0031). El default del proveedor puede cambiar.
- **Una respuesta que no terminó en `end_turn` no se usa**: ni cortada
  (`max_tokens`) ni rechazada (`refusal`). Cada nodo cae a su respaldo.
- **Lo que define el piso se calcula en una sola función** (`piso_efectivo`),
  usada por el árbitro y por la guarda 4.
- **Un LLM se mide con varias corridas.** Una sola da ruido: en los casos de borde
  el árbitro no es determinístico.
- **Un modelo nuevo se evalúa en sombra antes de reemplazar al actual**, con las
  entradas reales de producción y casos construidos para el error caro.
- **Un caso construido se arma como lo armaría el grafo**: si falta un agente o el
  perfil, desaparecen sus señales y sus políticas. Un caso inventado a mano
  exageró una señal y llevó a una conclusión equivocada que hubo que corregir.

### Footguns verificados en esta etapa

| Trampa | Detalle |
|---|---|
| Razonamiento de Sonnet 5 | Está activo por defecto y **cuenta dentro de `max_tokens`**; `messages.parse` falla con "JSON inválido" antes de que se pueda mirar `stop_reason` |
| Catch-all de FastAPI | `{full_path:path}` llega decodificado: `%2F` ya es `/` y `..` no se resuelve |
| Cloud Scheduler hacia una API de Google | La API es `run.googleapis.com` (no `cloudrun.`), y `*.googleapis.com` pide `oauth_token`, no `oidc_token` |
| Scheduler en pausa | `gcloud scheduler jobs run` falla con un job `PAUSED`: hay que reanudarlo, correrlo y volver a pausarlo |
| Caché de `setup-uv` | Con `prune-cache: true` (el default) la caché pesa ~0 MB y el CI descarga todo de PyPI; un día lento, 15 minutos |
| API de TypeSafe | Sólo alias (`jev-latest`, `jev-preview`); la versión real viene en cada respuesta |
| `npm ci` con un dev server abierto (Windows) | Falla a mitad de camino (`EPERM`) y deja `node_modules` a medias |

---

## 5. La demo publicada: el primer día

Publicada en LinkedIn el 02/10, con el video del grafo y los links en el primer
comentario.

| | Línea base | Día 1 |
|---|---|---|
| Créditos de Anthropic | USD 19.43 | USD 19.21 (−0.22: 14 análisis a ~0.016) |
| Neon | 0.61 CU-h | 1.05 CU-h (~1,8 h con la base despierta) |
| Análisis | — | 14, todos con el veredicto esperado; 0 degradados, 0 errores |

LinkedIn: 673 impresiones, 324 personas alcanzadas, 206 vistas del video (promedio
18 s sobre un video de 10,6 s). Llegaron ~20 visitas a la demo y ~3 personas al
repositorio.

---

## 6. Hallazgos y deuda

- **La versión del árbitro no se sella en la decisión.** Sólo la explicación al
  cliente lo hace (`explanation_prompt_version`). Un cambio de modelo o de prompt
  del árbitro no queda registrado en las decisiones que produjo.
- **Variación residual del árbitro:** 1 de 60 corridas en un caso ambiguo,
  siempre por encima del piso.
- **`/metrics` es público en producción.** No expone datos sensibles, pero nadie lo
  lee: sólo sirve en local (ADR-0024).
- **Dependabot está desactivado** en el repositorio.
- **El CI descarga todas las dependencias en cada corrida** (ver footguns).
- **Haiku 4.5**, que usa fetch-intel, figura con retiro "no antes del 15/10/2026".
  No está deprecado, y Anthropic avisa con 60 días.
- **El corpus de inteligencia externa sigue vacío**: la corrida de prueba del
  ADR-0029 dejó 0 indicadores de 130 resultados (deuda del acta 13).
- **Nadie resolvió un caso de la cola HITL** en el primer día: los visitantes
  quizás no la descubren.

---

## 7. Mapa de archivos al cierre

```
src/multiagent_fraud_detection/
├── api/app.py                     # catch-all dentro de dist/; 404 JSON bajo /api/
├── api/casos_interrumpidos.py     # cierre de casos en curso al arrancar
├── api/routers/cases.py           # sin espera global; el único 429 es el techo
├── api/showcase.py                # T-1031
├── arbiter/{judge,prompt}.py      # create + transform_schema; adaptativo, 2 000; v3
├── debate/pro_{fraud,customer}.py # sin razonamiento, 600
├── domain/engine.py               # piso_efectivo, AGENTES_DE_SENALES
└── explain/{customer,narrator,audit}.py   # customer:2; stop_reason; piso en la auditoría

dashboard/src/
├── routes/{Inicio,Observability,NoEncontrada}.tsx
├── components/{CasoEnVivo,DecisionBadge}.tsx
└── lib/etiquetas.ts

infra/{azure,gcp}/main.tf          # fetch-intel a demanda; scheduler de GCP corregido y en pausa

docs/
├── adr/0029…0032
├── incidentes/0011…0012
├── evaluaciones/                  # Jev, Sonnet 5.5, consistencia del árbitro
└── reviews/
    ├── tiempo-real-vs-investigacion.md
    └── 14-despues-de-publicar.md  # este archivo
```

---

## 8. Qué sigue

1. **Evaluación a la semana de publicar**, contra la línea base (descontando el
   gasto de los experimentos de estos días).
2. **Sellar la versión del árbitro** en la decisión (migración, contrato y ADR).
3. **Pendientes chicos:** caché del CI, `/metrics` sólo fuera de producción,
   Dependabot.
4. **Lo que falta de la rúbrica:** el informe (ítems 1 y 9), las referencias en
   APA (11) y el video de exposición (12).

---

## 9. Documentación asociada

- ADR-0029 a ADR-0032 (§3) y los incidentes 0011 y 0012 en [`docs/incidentes/`](../incidentes/)
- [`CHANGELOG.md`](../CHANGELOG.md) — contrato v0.16
- [`evaluaciones/`](../evaluaciones/) — Jev, Sonnet 5.5 y la consistencia del árbitro
- [`tiempo-real-vs-investigacion.md`](tiempo-real-vs-investigacion.md) — la duda que llevó al desvío D-08
- `13-operacion-y-publicacion.md` — etapa anterior
- Demo principal (Azure): https://ca-fraud-detection-api.graywave-cc1ab2d2.eastus2.azurecontainerapps.io
- Demo de aprendizaje (GCP): https://fraud-detection-api-im2rcartea-uc.a.run.app
