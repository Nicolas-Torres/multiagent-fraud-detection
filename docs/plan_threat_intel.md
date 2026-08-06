# Plan de ejecución — `feature/threat-intel`

**Documento efímero.** Muere al cerrar la etapa: su contenido se convierte en
`docs/reviews/07-threat-intel.md`. No sobrevive al merge.

Las decisiones de diseño están cerradas en
[ADR-0014](adr/0014-la-inteligencia-externa-se-recoge-en-build-y-se-consulta-congelada.md)
y [ADR-0015](adr/0015-la-evidencia-externa-entra-al-veredicto-por-el-vocabulario-del-catalogo.md).
Leer los dos antes de tocar código: acá está el orden, no el porqué.

---

## Estado

| # | Paso | Estado |
|---|---|---|
| 1 | Tabla `threat_indicators` | ✅ migración aplicada (`alembic current` = head) |
| 2 | Enforcement del allowlist | ✅ 15 tests verdes |
| 3 | Puerto `Searcher` | ✅ 18 tests verdes |
| 4 | `web_search_allowlist` + `issuer_bank` | ✅ migración aplicada, gates verdes |
| 5 | Caché de indicadores en `GraphContext` | ✅ 9 tests verdes |
| 6 | `fetch_threat_intel.py` | ✅ `--dry-run` y `--fake` × 2 verificados |
| 7 | Predicado y vinculación de FP-10 | ✅ 7000/7000, FP-10 activa y afirmada |
| 8 | El nodo | ✅ 8 tests, smokes del grafo verdes |
| 9 | Sello, persistencia y explicabilidad | ✅ migración aplicada, 224 tests verdes |
| 10 | Cierre documental | ⬜ |

`issuer_bank` se adelantó del paso 7 al 4: el fetch necesita la lista de emisores
y esa lista sale de la base.

---

## 1. Tabla `threat_indicators`

- `src/multiagent_fraud_detection/enums.py` — `IndicatorType(StrEnum)` al final,
  después de `Segment`: `ISSUER`, `DEVICE`, `MERCHANT`.
- `src/multiagent_fraud_detection/db/models/threat_indicator.py` — nuevo.
- `src/multiagent_fraud_detection/db/models/__init__.py` — import y `__all__`.
  **Sin esto el `--autogenerate` no ve la tabla.**

PK surrogate `BigInteger`; unique en
`(indicator_type, value, observed_at, snapshot_version)`, que es lo que hace
idempotente al fetch; **sin índice de lectura** —son decenas de filas y se
cachean, mismo criterio que `merchant_blacklist`—.

`observed_at` (publicación) ≠ `retrieved_at` (recuperación). La ventana de FP-10
evalúa la primera.

```
feat(db): add threat_indicators governance table
```

---

## 2. Enforcement del allowlist ✅

- `src/multiagent_fraud_detection/intel/__init__.py` — vacío.
- `src/multiagent_fraud_detection/intel/governance.py`
- `tests/test_governance.py`

Función pura, sin red ni base. El proveedor filtra por costo; la garantía es esta
función, aplicada sobre lo que efectivamente volvió.

---

## 3. Puerto `Searcher`

- `src/multiagent_fraud_detection/intel/snapshot.py` — `MODEL`, `TEMPLATE_TAG`,
  `GENERATION`, `SNAPSHOT_VERSION`, `QUERY_TEMPLATE` y `build_query`.
  **La plantilla va en este archivo, pegada a su tag**: separarlos es cómo se
  edita el texto sin subir la generación.
- `src/multiagent_fraud_detection/intel/searcher.py` — protocolo, adaptador de
  Anthropic, `FakeSearcher` y `parse_page_age`.

La herramienta se declara con `allowed_domains` (dominios pelados, sin esquema;
excluyente con `blocked_domains` — los dos juntos dan 400).

**La URL sale del bloque `web_search_result`, nunca de la prosa del modelo**, y
el `summary` que se persiste es el **título de la fuente**. Nada generado entra
al rastro de auditoría.

`parse_page_age` devuelve `None` en vez de adivinar; el llamador rechaza la fila.

```
feat(intel): add the Searcher port and its Anthropic adapter
```

---

## 4. `web_search_allowlist` + `issuer_bank`

- `src/multiagent_fraud_detection/db/models/web_search_allowlist.py` — molde
  exacto de `merchant_blacklist`: PK natural `domain`, `active`, `reason`,
  `added_by`, `added_at`. Nombre en singular, como su hermana.
- `src/multiagent_fraud_detection/db/repositories/web_search_allowlist.py` —
  `active_domains(session) -> frozenset[str]`. **Sin caché**: la lee un script de
  build una vez por corrida, no el grafo.
- `src/multiagent_fraud_detection/db/models/transaction.py` — `issuer_bank:
  Mapped[str | None] = mapped_column(String(16))`, después de `merchant_id`.
- `src/multiagent_fraud_detection/schemas/transaction.py` — `TransactionIn` gana
  el campo. **Es el olvido silencioso de la etapa**: `_dataset.py` construye
  `TransactionIn` y `seed.py` hace `model_dump()`, así que sin el campo en el
  schema la columna queda `NULL` en las 7 000 filas y nada falla.
- `scripts/_dataset.py` — borrar el comentario de la línea ~71 que dice que
  `issuer_bank` se descarta por ADR-0005, y agregarlo en `leer_transacciones()`
  después de `merchant_id`.
- `scripts/seed.py` — `threat_indicators` y `web_search_allowlist` en el
  `TRUNCATE` de `_reset` (~línea 175); sembrar el allowlist después del `_upsert`
  de `MerchantBlacklist` (~línea 292). **`threat_indicators` no se siembra**: la
  puebla el fetch.

Migración *expand*: la columna entra nullable. Después, `alembic check` limpio y
regenerar el diagrama del modelo de datos, que es gate de CI.

Sembrar el allowlist con supervisores y asociaciones bancarias, no blogs.
`reason` es donde se responde quién autorizó la fuente y por qué.

```
feat(db): add web_search_allowlist and issuer_bank
```

---

## 5. Caché de indicadores

- `src/multiagent_fraud_detection/db/repositories/threat_indicator.py` —
  `Indicator`, `IndicatorIndex`, `active_indicators`, `IndicatorCache`.
  La fábrica de sesiones se llama **`AsyncSessionLocal`** (`db/session.py`).
- `src/multiagent_fraud_detection/graph/context.py` — campo `indicators`.

No reusa `BlacklistCache`: aquélla cachea un `frozenset` y ésta un índice
`(tipo, valor) → observaciones`, porque el lookup necesita la ventana temporal.
Comparten patrón, no implementación.

El `WHERE snapshot_version = SNAPSHOT_VERSION` **es un invariante, no un
filtro**: sin él un veredicto consultaría dos generaciones y el sello diría una
sola.

El campo entra junto con el test que arma el `GraphContext` completo — el acta 06
§6.3 ya avisó de 161 verdes con un contexto al que le faltaban tres campos.

```
feat(graph): expose the indicator cache to the graph context
```

---

## 6. `fetch_threat_intel.py`

`scripts/fetch_threat_intel.py`. Único punto del sistema que toca la red en el
camino del dato.

Emisores desde la base, `--dry-run` que imprime las queries sin gastar búsquedas,
upsert por `ON CONFLICT` sobre el constraint, informe de gobernanza con lo
aceptado y lo rechazado por motivo. Allowlist vacío → falla ruidosamente: sin esa
guarda pagaría cada búsqueda y guardaría cero filas, que se lee igual que "no hay
alertas".

**Verificación que importa**: correrlo dos veces y confirmar que el conteo de
filas no cambia.

```
feat(intel): fetch and freeze the external intelligence corpus
```

---

## 7. Predicado y vinculación de FP-10

- `src/multiagent_fraud_detection/domain/predicates.py` — `Input` gana
  `"indicators"`; `EvalContext` gana el campo; `INTEL_INPUTS`; predicado
  `issuer_under_alert` (molde de `merchant_blacklisted`, severidad `MEDIUM`).
- `src/multiagent_fraud_detection/domain/catalog.py` — `Owner` gana
  `THREAT_INTEL`; `Policy.owner` pasa a tres ramas, con `indicators` en
  precedencia.
- `data/policies/policy_bindings_2025.1.json` — FP-10 gana `condition`, pierde
  `excluded_reason`. **El documento no se toca**: la huella tiene que seguir
  coincidiendo, y un test lo afirma.

La ventana de 24 h se resuelve *as-of* contra `transaction.timestamp`, nunca
contra `now()`.

**`check_policies --source=db` sigue en 7000/7000 y afirma explícitamente que
FP-10 no disparó.** No puede disparar: el dataset es de diciembre de 2025 y
cualquier indicador capturado hoy queda a ocho meses.

```
feat(domain): bind FP-10 to the external indicator corpus
```

---

## 8. El nodo

`src/multiagent_fraud_detection/graph/nodes.py` — `external_threat_intel` deja de
ser stub: lee la caché, evalúa las políticas de owner `THREAT_INTEL`, proyecta a
`citations_external`, devuelve `threat_intel_version`.

Sigue en el superstep 0. Sin red, así que `@degrades` vuelve a ser red para lo
imprevisto. Se retira la escritura de `discarded_sources`, que sale de
`graph/state.py`.

```
feat(graph): wire the external threat intel node
```

---

## 9. Sello, persistencia y explicabilidad

- `src/multiagent_fraud_detection/db/models/decision.py` —
  `threat_intel_version: Mapped[str | None] = mapped_column(String(64))`, más
  migración.
- `src/multiagent_fraud_detection/graph/nodes.py` — el persistidor lo escribe.
- `src/multiagent_fraud_detection/explain/audit.py` — bloque de evidencia
  externa: qué indicador, de qué fuente, con qué versión de snapshot.
- `explain/customer.py` **no cambia**: `ISSUER_UNDER_ALERT` no entra a
  `SAFE_THEMES` y cae al tema genérico. Nombrar la alerta al titular revela
  capacidad de detección y afirma algo sobre un tercero identificable.

```
feat(decision): seal which intelligence snapshot informed the verdict
```

---

## 10. Cierre

```bash
uv run pytest
uv run python scripts/check_policies.py --source=db
uv run python scripts/smoke_threat_intel.py
uv run python scripts/smoke_decision.py
```

El smoke de decisión gana un cuarto escenario: se siembra un indicador con
`observed_at` cercano a la transacción y el caso pasa de `APPROVE` a `CHALLENGE`
con FP-10 en `citations_internal`. Es la demostración de la capacidad.

Después: acta `docs/reviews/07-threat-intel.md`, contrato → **v0.8** con las ocho
enmiendas, `CHANGELOG.md`, tag `contrato-v0.8`, tabla de estado del README,
`graph_topology.png` regenerado, C4 container revisado, y **borrar este archivo**.
