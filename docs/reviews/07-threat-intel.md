# Repaso — Etapa "Inteligencia externa"
**Sistema Multi-Agente de Detección de Fraude · handoff de continuidad**

> Documento de cierre de etapa. Destila lo decidido y construido en
> `feature/threat-intel`, para retomar en el chat siguiente con el contexto ya
> condensado.
>
> Predecesor: `06-rag-de-politicas.md`.
> Decisiones de fondo: `adr/0014-*`, `adr/0015-*`.

---

## 1. Qué se cerró en esta etapa

El **Threat Intel Agent de punta a punta**: recolección gobernada en build,
consulta congelada en runtime, y FP-10 —hasta ayer excluida por evidencia no
reproducible— vinculada al catálogo como una política más.

| Pieza | Archivo | Verificado |
|---|---|---|
| Tabla `threat_indicators` (gobernanza) | `db/models/threat_indicator.py` | migración aplicada, `alembic check` limpio |
| Enforcement del allowlist (función pura) | `intel/governance.py` | 15 tests |
| Puerto `Searcher` + adaptador Anthropic | `intel/searcher.py`, `intel/snapshot.py` | 18 tests |
| `web_search_allowlist` + `issuer_bank` | `db/models/{web_search_allowlist,transaction}.py` | migración aplicada, 7000/7000 |
| Caché de indicadores en `GraphContext` | `db/repositories/threat_indicator.py` | 9 tests, `GraphContext` real construido |
| `fetch_threat_intel.py` | `scripts/fetch_threat_intel.py` | `--dry-run`, `--fake` × 2 idempotente |
| Predicado `issuer_under_alert` + FP-10 vinculada | `domain/predicates.py`, `policy_bindings_2025.1.json` | 7000/7000, corpus saturado |
| Nodo `external_threat_intel` | `graph/nodes.py` | 8 tests, smokes del grafo |
| Quinto sello: `threat_intel_version` | `db/models/decision.py`, `explain/audit.py` | migración aplicada, smoke con 4 escenarios |

**Cadena de migraciones**: `8db41fe7465f` → `threat_indicators` → `web_search_allowlist` + `issuer_bank` → sello del snapshot externo (`f193c092654b`, head).

---

## 2. El giro: una invariante que nadie puede ver fallar no es una invariante

ADR-0015 dice algo fuerte y fácil de pasar por alto: *FP-10 no puede disparar
sobre el dataset **aunque la tabla esté llena**.* Las 7 000 transacciones son de
diciembre de 2025; cualquier indicador capturado hoy queda a ocho meses de la
ventana de 24 h.

El plan pedía que `check_policies` "afirmara explícitamente" esa propiedad. La
forma obvia de hacerlo —correr el gate con `threat_indicators` vacía y verificar
que FP-10 no aparece en `matched_policies`— es exactamente el error que la
acta 06 §6.2 ya había nombrado: *una prueba que no puede fallar es peor que no
tenerla.* Con la tabla vacía, la política tampoco dispara por falta de
indicadores que mirar; el gate daría verde sin haber ejercitado la ventana
temporal en absoluto.

La alternativa que se implementó —**corpus saturado**— construye, en memoria y
sin tocar Postgres, un indicador por cada emisor del dataset, fechado **hoy**.
Es el peor caso posible: si la ventana de 24 h no filtrara por fecha, dispararía
en las 7 000 filas. Verificado en las dos direcciones antes de darlo por bueno:

- Con el corpus fechado hoy → **0 disparos**. El gate queda verde.
- Con el mismo corpus fechado *dentro* del rango del dataset (2025-12-02) →
  **239 disparos**. El gate se pone rojo, como tiene que poder hacerlo.

La segunda corrida no quedó en el código: fue una verificación manual, ad hoc,
antes de aceptar el diseño. Vale la pena que quede escrita acá, porque es la
evidencia de que el gate mide lo que dice medir.

---

## 3. Las decisiones jugosas y su porqué

### 3.1 El allowlist gobierna la escritura, no la lectura

Es la relectura completa de lo que el enunciado del reto describe. Leído
literalmente, el Threat Intel Agent busca en la web *durante* el análisis del
caso, con un allowlist que filtra esa búsqueda en runtime. ADR-0014 lo invierte:
la búsqueda ocurre **una vez, en build** (`fetch_threat_intel.py`); en runtime el
nodo sólo hace *lookup* contra lo que ya se congeló. El allowlist se aplica en
el camino de **escritura** — lo que no pasa la lista no llega a
`threat_indicators` — así que en runtime no hay nada que descartar. Por eso
`DiscardedSource` se retiró de `graph/state.py`: existía para un rechazo que ya
no ocurre ahí.

La razón no es sólo arquitectónica. Los gates determinísticos del proyecto
tienen que dar el mismo número dos veces, y una búsqueda web en vivo lo rompe
por construcción — el mismo problema que ADR-0005 ya había detectado para esta
misma política.

### 3.2 `indicators` gana precedencia sobre la partición contexto/comportamiento

`Owner` pasa de dos ramas a tres. La derivación no fue "agregar un tercer
`if`": `issuer_under_alert` pide `transaction` **e** `indicators`, y la
partición binaria original (`requires <= CONTEXT_INPUTS` → Context, si no →
Behavioral) lo habría mandado a Behavioral, porque `indicators` no está en
`CONTEXT_INPUTS`. `owner_of()` chequea `INTEL_INPUTS` primero, con precedencia
explícita.

No es estética. `WorkingSignal.emitted_by` es el campo que el harness usa para
atribuir falsos positivos a un agente. Si la señal externa la reportara
Behavioral, ese campo mentiría en el único lugar donde alguien lo consulta para
medir — y el bug es silencioso: todo seguiría funcionando, sólo la atribución
sería falsa.

### 3.3 Las fuentes las entrega el predicado, no las recalcula el nodo

`issuer_under_alert` es el único que sabe, de las N observaciones de un emisor,
cuáles cayeron dentro de la ventana de 24 h. En vez de que el nodo repita esa
aritmética para armar `citations_external`, el predicado las deja en
`Hit.observed[SOURCES_KEY]` — ya filtradas, ya serializadas a JSON— y el nodo
sólo proyecta y deduplica por URL.

La alternativa —que el nodo recalculara la ventana a partir de
`ctx.indicators`— es la misma lógica escrita dos veces, con una single fuente de
verdad (el predicado) y una copia que puede desincronizarse el día que alguien
cambie `window_hours` en un solo lado.

### 3.4 `threat_intel_version` se sella aunque el corpus esté vacío

El quinto eje de auditoría repite la semántica de nulo de los otros cuatro,
pero el caso fácil de errar es distinto. `null` significa *no se consultó
snapshot* — el nodo degradó antes de completar el lookup —, **nunca** *no había
alertas*. Consultar y no encontrar nada **es** haber consultado, y por eso el
nodo sella la versión incluso cuando `active_indicators()` devuelve un índice
vacío.

La distinción importa para la auditoría: sin ella, un caso limpio (consultó y
no había nada) y un caso con el nodo caído (nunca consultó) se verían idénticos
en `decisions`, y esa es exactamente la clase de ambigüedad que los cinco
sellos existen para eliminar.

### 3.5 `page_age` es estricto, no adivina

El único formato que la documentación de Anthropic ejemplifica para `page_age`
es `"April 30, 2025"` — sin garantía de que sea el único que el proveedor
produzca. `parse_page_age` sólo acepta ese formato exacto; cualquier otra forma
("3 days ago", ISO, otro idioma) da `None`, y el llamador rechaza la fila en vez
de guardar una fecha adivinada.

Es el mismo criterio que gobierna todo el módulo `intel/`: una fecha mal leída
alimentaría la ventana de 24 h con un dato falso, y el costo de rechazar una
fila de más es infinitamente menor que el de sellar un veredicto con una fecha
inventada.

### 3.6 El texto al titular no cambia — omisión deliberada, no olvido

`ISSUER_UNDER_ALERT` no tiene entrada en `SAFE_THEMES`, así que cae al tema
genérico por el `.get(codigo, TEMA_GENERICO)` que ya existía. No hizo falta
tocar `explain/customer.py`. La razón está en ADR-0015: decirle al titular que
*el banco emisor de tu tarjeta está bajo alerta pública* es a la vez revelar
capacidad de detección y hacer una afirmación sobre un tercero identificable —
la misma deuda de revisión legal que `MERCHANT_BLACKLISTED` ya tiene abierta
desde la acta 06.

### 3.7 El plan se desincronizó del código, tres veces — y eso también es una lección

Los pasos 1, 3 y 5 del plan de la etapa llegaron marcados `⬜` en el documento de
seguimiento, pero el código ya existía —commiteado en sesiones anteriores— para
partes sustanciales de cada uno: la migración de `threat_indicators` ya estaba
aplicada; `intel/searcher.py` ya tenía el protocolo, el adaptador y
`FakeSearcher`; `db/repositories/threat_indicator.py` y el campo `indicators`
de `GraphContext` ya estaban commiteados junto con la migración del paso 1.

El patrón se repite lo suficiente como para nombrarlo: en una etapa que se
retoma entre sesiones, **el documento de plan es el artefacto que más rápido se
desactualiza**, porque el código puede avanzar sin que alguien vuelva a tocar la
tabla de estado. La mitigación que terminó funcionando no fue "confiar en el
plan", sino verificar el estado real antes de cada paso —`git log`, leer el
archivo, correr el gate— y tratar la discrepancia como información, no como
ruido. Ninguna de las tres veces costó trabajo perdido; costó, sí, una pausa
para reconciliar antes de escribir código nuevo encima de código que ya
funcionaba.

---

## 4. Convenciones nuevas fijadas

- **El allowlist gobierna la escritura; el enforcement en runtime no existe
  porque no hace falta.** Sale de ADR-0014, pero es un principio reusable: si
  un dato se congela en build, la gobernanza de su origen también se resuelve
  ahí, no en cada lectura.
- **Un axis de auditoría se sella incluso con resultado vacío.** `null` es
  siempre *"no se consultó"*, nunca *"se consultó y no había nada"*. Vale para
  los cinco sellos, no sólo para el nuevo.
- **El predicado que consulta un insumo externo entrega también su evidencia
  cruda**, lista para proyectarse a una cita. El nodo no repite la lógica de
  selección: sólo traduce.
- **Un valor con formato no garantizado se parsea estricto o se rechaza.**
  Ningún dato de un proveedor externo se adivina cuando no calza con el único
  formato documentado.
- **Un smoke que siembra datos con una forma que otro script consulta por
  `DISTINCT` tiene que limpiar al final de su propia corrida, no sólo al
  principio de la siguiente.** Ver footguns.

### Footguns verificados en esta etapa

| Trampa | Detalle |
|---|---|
| `ON CONFLICT DO UPDATE` con dos filas del mismo `INSERT` sobre la misma clave | Postgres lo rechaza ("command cannot affect row a second time"). Puede pasar si el proveedor repite una URL para el mismo emisor; `fetch_threat_intel.py` dedupea antes del upsert. |
| Un smoke que seedea `issuer_bank` sin limpiar al final | `fetch_threat_intel.py` arma su lista de emisores con `SELECT DISTINCT issuer_bank FROM transactions`. Una fila de smoke sin limpiar se cuela ahí, y una corrida real pagaría una búsqueda por un emisor que no existe. `smoke_decision.py` ahora limpia al final, no sólo al principio de la próxima corrida. |
| `IndicatorCache` con TTL puede servir un lookup vacío ya cacheado | Sembrar un indicador nuevo dentro de la misma corrida de un smoke no alcanza: hace falta `cache.invalidate()` explícito, el mismo mecanismo que usaría el alta desde el dashboard. |
| `→` (U+2192) en un `print` revienta en consola Windows (cp1252) | `UnicodeEncodeError` al final de un smoke, después de que todo lo demás ya corrió bien. Preexistente, encontrado al revalidar smokes en el paso 8. |
| Un plan de etapa desactualizado no avisa que lo está | Sin verificar contra `git log`/el código real, un paso marcado `⬜` puede estar total o parcialmente hecho. Ver §3.7. |

---

## 5. Verificación de la etapa

| Gate | Resultado |
|---|---|
| `pytest` | 224 verdes, sin red y sin base (161 al cierre de la etapa anterior) |
| `check_policies.py` | 7 000/7 000 desde archivo |
| `check_policies.py --source=db` | 7 000/7 000 desde Postgres; afirma explícitamente que FP-10 no disparó con el corpus saturado |
| `smoke_catalog_sources.py` | 11 políticas idénticas en ambas fuentes |
| `fetch_threat_intel.py --fake` (2ª vez) | mismo conteo de filas que la 1ª |
| `smoke_threat_intel.py` | idempotencia del fetch + `active_indicators()` no mezcla `SNAPSHOT_VERSION` con `FAKE_SNAPSHOT_VERSION` |
| `smoke_decision.py` | 4 escenarios en `DECIDED`, incluido el que pasa de `APPROVE` a `CHALLENGE` por una alerta externa |
| `smoke_degradation.py` | el Threat Intel Agent caído no aborta el grafo; los hermanos del superstep conservan sus señales |
| `alembic check` | limpio en las tres migraciones de la etapa |
| `export_data_model_diagram.py --check` | limpio, 14 tablas |

### La demostración de la capacidad

El escenario 4 de `smoke_decision.py` reutiliza el **mismo `case_id`** del
escenario 1 (caso limpio, `APPROVE`, sin políticas). Se siembra un indicador
sobre el emisor de esa transacción, fechado tres horas antes del cargo, se
invalida la caché, y se reprocesa:

| | Antes (escenario 1) | Después (escenario 4) |
|---|---|---|
| `decision` | `APPROVE` | `CHALLENGE` |
| `matched_policies` | `[]` | `['FP-10']` |
| `citations_internal` | `[]` | incluye `FP-10` |
| `citations_external` | — | 1 cita, con URL y resumen |
| `threat_intel_version` | sellado (corpus vacío) | sellado (mismo snapshot) |

Es la prueba de que ADR-0015 hace lo que promete: la inteligencia externa puede
mover un veredicto, no sólo la confianza. Sobre las 7 000 filas del dataset real
esto no se observa —FP-10 no tiene ground truth y no dispara por el desfase de
fechas—, así que la distribución de veredictos de `check_policies` **no
cambia** respecto de la etapa anterior. La demostración vive en el smoke, a
propósito.

---

## 6. Hallazgos y deuda

### 6.1 FP-10 activa y no medida, y eso es correcto

El dataset no la contempla y no se regenera —tocar la rama del generador
correría el stream aleatorio y cambiaría las 7 000 filas—. `test_ground_truth.py`
lo declara con una excepción nombrada (`SIN_GROUND_TRUTH = {"FP-10"}`) en vez de
dejar que el invariante "toda política dispara" se debilitara en silencio. El
informe del entregable 7 tiene que reportarlo como *"sin ground truth
reproducible"*, nunca como recall 0.

### 6.2 El allowlist sembrado son dos dominios peruanos, no una lista operativa real

`sbs.gob.pe` y `asbanc.com.pe` alcanzan para demostrar el mecanismo, pero una
operación real necesitaría una lista curada por alguien con criterio de
gobernanza —qué asociaciones bancarias por país, qué reguladores— que no es
una decisión técnica.

### 6.3 `SAFE_THEMES` sigue pendiente de revisión legal

La acta 06 ya lo había abierto para `MERCHANT_BLACKLISTED`; `ISSUER_UNDER_ALERT`
se resolvió con el mismo criterio (omisión) pero la misma revisión con
criterio legal, no técnico, sigue sin hacerse.

### 6.4 `merchant_blacklist` y `threat_indicators` son el mismo tipo de objeto

Los dos son "una entidad marcada, con motivo y quién la marcó". Consolidarlos
es candidato para el entregable 10; no se toca ahora porque `merchant_blacklist`
alimenta FP-07, que sí está medida, y una migración de esa tabla no es gratis.

### 6.5 Menor

- El allowlist no tiene un endpoint de alta todavía —su única fuente es
  `scripts/_dataset.py`—, igual que `merchant_blacklist` en la etapa anterior.
- `fetch_threat_intel.py` no reintenta una búsqueda que falla del lado del
  proveedor dentro de la misma corrida; sigue con el próximo emisor. Es
  consistente con "el script sigue, no aborta", pero un emisor que falla
  sistemáticamente no se distingue en el informe de uno que nunca tuvo alertas.
- La ventana de FP-10 (`window_hours=24`) es un parámetro de la vinculación,
  no del predicado — ya se puede ajustar sin tocar código, pero nadie definió
  todavía con qué criterio.

---

## 7. Mapa de archivos al cierre

```
src/multiagent_fraud_detection/
├── intel/
│   ├── governance.py              # enforce, is_allowed, normalize_allowlist
│   ├── searcher.py                # puerto, Anthropic, Fake, parse_page_age
│   └── snapshot.py                # MODEL, SNAPSHOT_VERSION, QUERY_TEMPLATE, build_query
├── domain/
│   ├── predicates.py               # + Input "indicators", INTEL_INPUTS, SOURCES_KEY, issuer_under_alert
│   └── catalog.py                  # + Owner.THREAT_INTEL, owner_of()
├── db/
│   ├── models/{threat_indicator,web_search_allowlist,transaction,decision}.py
│   └── repositories/{threat_indicator,web_search_allowlist}.py
└── graph/
    ├── context.py                  # + indicators: IndicatorCache
    ├── nodes.py                    # external_threat_intel, _a_citations
    └── state.py                    # + threat_intel_version, − DiscardedSource

scripts/
├── fetch_threat_intel.py          # único punto que toca la red en el camino del dato
├── smoke_threat_intel.py          # idempotencia + aislamiento por generación
└── smoke_decision.py              # + escenario 4

data/policies/policy_bindings_2025.1.json   # FP-10: excluded_reason → condition
```

---

## 8. Qué sigue

**Inmediato**: publicar el contrato **v0.8**. Ocho enmiendas acumuladas y el
vigente era v0.7; sin decisiones conjuntas pendientes.

**Los agentes que faltan del reto**: Debate Agents y Arbiter agéntico. El
determinístico sigue siendo el brazo de control (ADR-0006); con el Threat Intel
Agent cerrado, el grafo ya tiene sus tres ramas del superstep 0 completas.

**API FastAPI + HITL** y **CI/imagen/despliegue** siguen sin empezar — son las
dos filas `⬜` que quedan en la tabla de estado del README, y no dependen de
esta etapa.

**Deuda declarada para el informe**: FP-10 sin ground truth (§6.1), el allowlist
como demo y no como lista operativa (§6.2), y la revisión legal pendiente de
`SAFE_THEMES` (§6.3).

---

## 9. Documentación asociada

- `adr/0014-la-inteligencia-externa-se-recoge-en-build-y-se-consulta-congelada.md`
- `adr/0015-la-evidencia-externa-entra-al-veredicto-por-el-vocabulario-del-catalogo.md`
- `enmiendas_pendientes.md` — vacío tras publicar; ocho enmiendas hacia v0.8, en `CHANGELOG.md`
- `06-rag-de-politicas.md` — etapa anterior
