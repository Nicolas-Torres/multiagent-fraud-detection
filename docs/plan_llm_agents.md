# Plan de ejecución — `feature/llm-agents`

**Documento efímero.** Muere al cerrar la etapa: su contenido se convierte en
`docs/reviews/08-llm-agents.md`. No sobrevive al merge.

Las decisiones de diseño están cerradas en
[ADR-0006](adr/0006-reparto-deterministico-y-llm.md) (qué nodo es LLM y por qué),
[ADR-0013](adr/0013-que-se-mide-con-metricas-duras-y-que-con-llm-as-judge.md)
(qué mide un gate y qué mide DeepEval) y
[ADR-0016](adr/0016-el-arbitro-con-llm-escala-pero-no-cruza-el-piso-determinista.md)
(el piso del Arbiter). Leer los tres antes de tocar código: acá está el orden,
no el porqué.

**Sin migraciones.** Esta etapa no agrega columnas: `debate_pro_fraud` /
`debate_pro_customer` ya existen en `decisions` desde que el grafo se armó (los
stubs ya escribían `"stub"`), y se decidió no sellar `arbiter_prompt_version` /
`debate_prompt_version` todavía — queda para cuando haya uso real de esos
sellos que justifique el eje nuevo.

---

## Estado

| # | Paso | Estado |
|---|---|---|
| 1 | Prompts de debate (reutilizan `Narrator`) | ✅ |
| 2 | Nodo de debate real | ✅ |
| 3 | Puerto `Judge` + prompt del Arbiter | ✅ |
| 4 | Nodo `decision_arbiter` real + cuarta guarda de W2 | ✅ |
| 5 | Auditoría: párrafo de debate | ✅ |
| 6 | Golden set + evaluación DeepEval (deuda de ADR-0013) | ✅ |
| 7 | Cierre documental | ⬜ |

**Nota sobre el paso 6**: el golden set quedó en 7 casos reales, no ~15 —
elegidos a mano contra `data/ground_truth.csv`, uno por veredicto más el caso
de contradicción y los dos de FP-10, sin casos de agente degradado (queda
como extensión futura, no bloqueante). Corrida real contra los proveedores:
`fundamentacion_del_debate` dio mayormente 0.2-0.5, `calidad_del_juicio_del_arbiter`
0.8 en los casos con desvío del piso y dos fallos de parseo JSON del juez
-degradados a "error del juez", no crashean la corrida-. Material para el
entregable 7 (comparación y limitaciones), no un hallazgo a resolver acá.

---

## 1. Prompts de debate

- `src/multiagent_fraud_detection/debate/__init__.py` — vacío.
- `src/multiagent_fraud_detection/debate/pro_fraud.py` — `MODEL`,
  `TEMPLATE_TAG`, `GENERATION`, `PROMPT_VERSION`, `MAX_TOKENS`, `SYSTEM_PROMPT`,
  `build_prompt(evidence, policies, risk_score) -> str`, `fallback_argument()`.
- `src/multiagent_fraud_detection/debate/pro_customer.py` — mismo molde, el
  argumento contrario.
- `tests/test_debate_prompts.py`.

**No hay puerto nuevo.** `Narrator.narrate(system, user) -> str` ya es texto
libre sin estado — exactamente la forma que necesita un argumento de debate.
Introducir un segundo puerto con la misma firma sería duplicar sin motivo.

**Sí hay texto de respaldo**, a diferencia de `explanation_customer`: acá el
motivo no es divulgación sino que `debate_pro_fraud`/`debate_pro_customer` son
columnas `Mapped[str]` no nulables (`db/models/decision.py`), y el esquema del
contrato exige `min_length=1`. El respaldo tiene que decir explícitamente que
no se generó — *"no fue posible generar el argumento: el proveedor no
respondió"* — para que el Arbiter no lo lea como un argumento débil real.

**No aplica el control de divulgación de `explain/customer.py`.** Este texto no
lo lee el titular, lo lee el Arbiter y, en la auditoría, el analista. Puede
nombrar `policy_id` y códigos de señal como contexto — leerlos no es lo mismo
que generarlos, y es la regla que ya distingue `explain/audit.py` (los nombra
libremente) de `explain/customer.py` (nunca). El `SYSTEM_PROMPT` sí prohíbe
inventar evidencia que el caso no tiene, mismo criterio que ya usa
`explain/customer.py` para no inventar motivos.

```
feat(debate): add the pro-fraud and pro-customer argument prompts
```

---

## 2. Nodo de debate real

`src/multiagent_fraud_detection/graph/nodes.py` — `debate_pro_fraud` y
`debate_pro_customer` dejan de devolver `"stub"`. Mismo molde que
`explainability`: `@degrades` como red de última instancia, y adentro un
try/except propio alrededor de `asyncio.to_thread(runtime.context.narrator.narrate,
...)` que cae al texto de respaldo y agrega un `AgentError` — el `@degrades`
genérico no alcanza acá porque su rama de falla no deja ninguna clave en el
estado, y `pro_fraud_argument` no puede faltar.

Ganan el parámetro `runtime: Runtime[GraphContext]` que hoy no tienen — no
requiere tocar `graph/builder.py`, mismo caso que cuando `explainability` lo
ganó.

`tests/test_node_debate.py` (nuevo): camino feliz con `FakeNarrator`, caída del
proveedor → texto de respaldo + `agent_errors`, y que el `@degrades` externo
sigue protegiendo contra un fallo que no sea el de la llamada al proveedor.

```
feat(debate): wire the pro-fraud and pro-customer nodes to the narrator
```

---

## 3. Puerto `Judge` + prompt del Arbiter

- `src/multiagent_fraud_detection/arbiter/__init__.py` — vacío.
- `src/multiagent_fraud_detection/arbiter/prompt.py` — `MODEL`, `TEMPLATE_TAG`,
  `GENERATION`, `PROMPT_VERSION`, `MAX_TOKENS`, `SYSTEM_PROMPT` (explica la
  regla del piso al modelo mismo, aunque el código la vuelva a exigir después:
  un modelo que entiende la restricción viola la guarda menos seguido que uno
  que la descubre por rechazo), `build_prompt(floor, evidence, policies,
  citations, pro_fraud_argument, pro_customer_argument, degraded_agents,
  risk_score, base_confidence) -> str`.
- `src/multiagent_fraud_detection/arbiter/judge.py` — `ArbiterVerdict`
  (`BaseModel`: `decision: DecisionType`, `confidence: float` acotado `[0,1]`,
  `rationale: str`), `JudgeError`, protocolo `Judge.judge(system, user) ->
  ArbiterVerdict`, `AnthropicJudge` (perezoso, mismo patrón que
  `AnthropicNarrator`/`AnthropicSearcher`, salida estructurada vía
  `client.messages.parse()` contra `ArbiterVerdict` — es la forma vigente,
  `output_format` quedó deprecado), `FakeJudge` (veredicto fijo, para tests y
  smoke).
- `src/multiagent_fraud_detection/graph/context.py` — `GraphContext` gana
  `judge: Judge = field(default_factory=AnthropicJudge)`.
- `tests/test_judge.py`.

**Puerto nuevo, no reutilización de `Narrator`.** El Arbiter necesita un enum
válido y un float acotado, no prosa a parsear a mano — parsear texto libre para
extraer una decisión sería reintroducir con una regex el mismo riesgo que la
salida estructurada existe para evitar. Mismo criterio que separó `Embedder` de
`Narrator`: puerto distinto cuando la forma del contrato es distinta, aunque el
proveedor de abajo sea el mismo.

**El Arbiter lee `policy_id` como contexto, nunca los genera.** `ArbiterVerdict`
no tiene ningún campo que nombre una política — la evidencia y las citas ya
vienen resueltas por el motor, y el Arbiter solo elige `decision` de un enum
cerrado. Es la misma garantía que ya cumple `explainability`, aplicada a un
campo estructurado en vez de a prosa.

```
feat(arbiter): add the Judge port and the arbiter verdict prompt
```

---

## 4. Nodo `decision_arbiter` real + cuarta guarda de W2

- `src/multiagent_fraud_detection/domain/params.py` — `precedencia(decision:
  DecisionType) -> int`, pegada a `PRECEDENCE`: el índice en la tupla ya
  existente, menor índice = más restrictivo.
- `src/multiagent_fraud_detection/graph/nodes.py`:
  - `decision_arbiter` conserva sus dos degradaciones actuales tal cual —
    faltan cita interna o falta `base_confidence` son evidencia incompleta, no
    fallas del proveedor de juicio, y siguen resolviéndose antes de llamar al
    LLM.
  - Con evidencia completa: calcula `piso = prescribed_action(catalog,
    tuple(politicas))` y llama a `runtime.context.judge.judge(...)` envuelto en
    `asyncio.to_thread` + try/except propio, **no** `@degrades` — este nodo
    sigue bajo "nodos fatales" para cualquier fallo que no sea el del
    proveedor (un `prescribed_action` que lanza es un bug del catálogo, y eso
    tiene que tumbar el caso). Si el Judge falla: degrada a
    `ESCALATE_TO_HUMAN` con `confidence = piso` y
    `confidence_rationale = "proveedor de juicio no disponible: se escala con
    el piso determinista"` + `AgentError(agent=ARBITER, ...)`. Es la misma
    apuesta que ADR-0016 ya hizo para el desacuerdo del modelo, llevada un paso
    más: el peor caso de un proveedor caído también es escalar de más, nunca
    aprobar de menos.
  - Con el Judge respondiendo: `decision = veredicto.decision`, `confidence =
    veredicto.confidence`, `confidence_rationale = veredicto.rationale` sólo si
    `veredicto.confidence != base` — la tercera guarda existente exige
    justificación cuando difieren, no exige omitirla cuando no difieren, así
    que guardar el rationale sólo en el primer caso mantiene el texto de
    auditoría enfocado en lo que realmente cambió.
  - `_verificar_invariantes` gana el parámetro `catalog: PolicyCatalog` — hoy
    sólo recibe `state`, y la cuarta guarda necesita recalcular
    `prescribed_action` para comparar. `persist_decision` se lo pasa desde
    `runtime.context.catalog`, que ya tiene a mano.
  - Cuarta guarda: `decision != ESCALATE_TO_HUMAN` (exenta, como las otras
    tres) ⟹ `precedencia(decision) >= precedencia(prescribed_action(catalog,
    matched_policies))`. Si dispara, es un bug del Arbiter — el caso pasa a
    `FAILED`, comportamiento correcto que ADR-0016 ya asumió como costo.
- `tests/test_citations.py` (ahí ya viven las pruebas de `_verificar_invariantes`)
  gana el caso de la cuarta guarda: un veredicto por debajo del piso levanta.
- `tests/test_node_arbiter.py` (nuevo): el Arbiter sube de nivel con
  justificación (pasa), degradación del Judge → `ESCALATE_TO_HUMAN` con el piso,
  `confidence_rationale` ausente cuando el veredicto coincide con `base`.

```
feat(arbiter): wire the LLM arbiter with the deterministic floor and its guard
```

---

## 5. Auditoría: párrafo de debate

`src/multiagent_fraud_detection/explain/audit.py` — línea nueva con los dos
argumentos, sólo cuando ambos están presentes (un caso que no llegó a debate no
tiene qué mostrar). El analista que lee por qué el Arbiter escaló más allá del
piso necesita ver qué dijo el debate, no sólo el `confidence_rationale` que lo
resume.

`tests/test_explain.py` gana el caso.

```
feat(explain): surface the debate arguments in the audit trail
```

---

## 6. Golden set + evaluación DeepEval

Deuda declarada por ADR-0013: *"de la etapa de agentes con LLM, no de esta"*.
Esa etapa es esta.

- `data/eval/golden_set_llm_agents.json` — ~15 `transaction_id` del dataset de
  7 000, elegidos a mano y no muestreados: uno por cada veredicto esperado, un
  par con `has_contradiction`, un par de FP-10 (con snapshot sembrado aparte,
  mismo montaje que el cuarto escenario de `smoke_decision.py`), un par con
  agente degradado simulado.
- `scripts/eval_golden_set.py` (nuevo, **fuera de `pytest`** — toca red y LLM,
  mismo carril que los smokes): corre el grafo completo sobre el golden set,
  junta los dos argumentos de debate y el veredicto del Arbiter, y puntúa con
  DeepEval (`GEval` u otra métrica declarada) contra dos criterios: el
  argumento no inventa evidencia que el caso no tiene, y la decisión final
  respeta el piso. Reporta; no bloquea — `check_policies.py`/`test_ground_truth.py`
  siguen siendo el único gate que sí bloquea, y siguen midiendo
  `domain/engine.py`, no el Arbiter.

```
test(eval): curate the golden set and score the arbiter with DeepEval
```

---

## 7. Cierre

```bash
uv run pytest
uv run python scripts/check_policies.py --source=db
uv run python scripts/smoke_decision.py
uv run python scripts/smoke_agents.py
```

`smoke_decision.py` gana un quinto escenario: un caso donde el piso
determinista prescribe `APPROVE`/`CHALLENGE` y el debate expone una
contradicción que el Arbiter usa para escalar un nivel, con
`confidence_rationale` poblado. Es la demostración de la capacidad que
ADR-0016 le dio al rol, igual que el cuarto escenario lo fue para FP-10.

Después: revisar si `docs/contrato_de_interfaz.md` describe en algún lado al
Arbiter o al debate como deterministas/stub y corregirlo (el objeto `debate` y
`decision.rationale` del contrato ya existían — esto es la primera vez que se
llenan de verdad, no un campo nuevo); `CHANGELOG.md`; tabla de estado del
README; retargetear `docs/briefing_threat_intel.md` a la etapa que sigue después
de ésta (sigue nombrando threat-intel como "próxima etapa", quedó pendiente al
cerrar la anterior); acta `docs/reviews/08-llm-agents.md`; diagramas
regenerados; y **borrar este archivo**.
