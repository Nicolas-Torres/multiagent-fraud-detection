# Repaso — Etapa "Agentes con LLM"
**Sistema Multi-Agente de Detección de Fraude · handoff de continuidad**

> Documento de cierre de etapa. Destila lo decidido y construido en
> `feature/llm-agents`, para retomar en el chat siguiente con el contexto ya
> condensado.
>
> Predecesor: `07-threat-intel.md`.
> Decisiones de fondo: `adr/0006-*`, `adr/0013-*`, `adr/0016-*`.

---

## 1. Qué se cerró en esta etapa

Los **dos agentes de debate y el Arbiter con LLM**, de punta a punta:
`debate_pro_fraud`, `debate_pro_customer` y `decision_arbiter` dejan de ser
stubs. El Arbiter decide el veredicto final sobre un **piso** determinístico
—lo que el catálogo prescribe por precedencia— que puede escalar con
justificación auditable y nunca bajar (ADR-0016). Golden set curado y
evaluación de calidad con DeepEval, deuda que ADR-0013 había declarado para
esta etapa.

| Pieza | Archivo | Verificado |
|---|---|---|
| Prompts de debate (reutilizan `Narrator`) | `debate/{pro_fraud,pro_customer}.py` | 11 tests |
| Nodos de debate reales | `graph/nodes.py` | 5 tests |
| Puerto `Judge` (salida estructurada) + prompt del Arbiter | `arbiter/{judge,prompt}.py` | 9 tests |
| Nodo `decision_arbiter` real + cuarta guarda de W2 | `graph/nodes.py`, `domain/params.py` | 6 + 3 tests, smoke con 5 escenarios |
| Párrafo de debate en la auditoría | `explain/audit.py` | 2 tests |
| Golden set + evaluación DeepEval | `data/eval/`, `scripts/eval_golden_set.py` | corrida real, 19/21 mediciones |

**Sin migraciones.** `debate_pro_fraud`/`debate_pro_customer` ya existían como
columnas no nulables desde que el grafo se armó; no se agregó
`arbiter_prompt_version` ni `debate_prompt_version` (§6.4).

---

## 2. El giro: un smoke no puede afirmar lo que el LLM decide, sólo lo que el código garantiza

`smoke_decision.py` traía cuatro escenarios que comparaban `decision.decision`
contra un valor exacto — `assert decision == BLOCK`, `== CHALLENGE`. Con el
Arbiter determinístico eso era correcto: el veredicto **era** el piso, sin
margen. En cuanto `decision_arbiter` pasó a ser el Arbiter con LLM
(ADR-0016), dos de esas cuatro comparaciones —el escenario 1 (piso `APPROVE`)
y el escenario 4 (piso `CHALLENGE`, vía FP-10)— quedaron **estructuralmente
mal planteadas**: el Arbiter puede legítimamente escalar por encima del piso,
así que una igualdad estricta convertiría una escalada correcta en un smoke
rojo.

El error no se manifestó en la corrida —el Arbiter coincidió con el piso las
dos veces (§5)— pero eso fue suerte de esa corrida, no una propiedad del
diseño: la próxima ejecución, con la misma evidencia, puede escalar. La
corrección fue reemplazar la igualdad por la comparación de precedencia que
la cuarta guarda ya hace cumplir —`precedencia(decision) >=
precedencia(piso)`— e imprimir una nota informativa (no un fallo) cuando el
Arbiter escala. Los escenarios 2 y 3 no se tocaron: su piso es `BLOCK`, el
techo de la escala, así que ahí no hay a dónde escalar y la igualdad estricta
sigue siendo correcta.

La lección generaliza: **un gate no puede comparar contra la salida de un
componente no determinístico con igualdad estricta si ese componente tiene
permiso de apartarse en una dirección conocida.** Lo que el gate puede
afirmar es la restricción que el sistema sí garantiza —acá, la cuarta
guarda—, no un valor puntual que depende del juicio del modelo.

---

## 3. Las decisiones jugosas y su porqué

### 3.1 El piso, no el veredicto

`prescribed_action(catalog, matched_policies)` —el mismo cálculo que
construye `expected_decision` para el entregable 7— deja de ser el veredicto
final y pasa a ser una **cota mínima de cautela**. El Arbiter LLM elige la
decisión con la restricción `precedencia(decision) >= precedencia(piso)`:
puede subir de nivel con justificación, nunca bajar uno que una política ya
ganó. Es la decisión central de ADR-0016, y la que hace que "juicio bajo
evidencia contradictoria" (el rol que ADR-0006 le asignó) tenga un efecto
observable sin reabrir el caso que el invariante de contención de §2.5 existe
para cerrar.

### 3.2 Un puerto nuevo para el Arbiter, no reutilizar `Narrator`

`Narrator.narrate(system, user) -> str` es la forma correcta para el debate
—texto libre, sin estado— pero el Arbiter necesita un `DecisionType` válido y
un `float` acotado, no prosa a parsear a mano. `Judge.judge(system, user) ->
ArbiterVerdict` usa salida estructurada de la API de Mensajes
(`client.messages.parse(..., output_format=ArbiterVerdict)`), que valida
contra el schema en el borde en vez de reintroducir con una expresión regular
el mismo riesgo que la salida estructurada existe para evitar. Mismo criterio
que ya separó `Embedder` de `Narrator`: puerto distinto cuando la forma del
contrato es distinta, aunque el proveedor de abajo sea el mismo.

### 3.3 La degradación del Arbiter extiende la apuesta del ADR, no la contradice

`decision_arbiter` sigue bajo "nodos fatales" —si `prescribed_action` lanza,
es un bug del catálogo y el caso tiene que caer— pero gana un try/except
*propio* (no el `@degrades` genérico) alrededor de la llamada al `Judge`: si
el proveedor no responde, el nodo degrada a `ESCALATE_TO_HUMAN` con el piso
como confianza, no deja que la excepción se propague. No lo pedía
explícitamente ADR-0016, pero es la misma apuesta que el ADR ya hizo para el
desacuerdo del modelo —"el peor caso es escalar de más, nunca aprobar de
menos"— llevada un paso más: un proveedor caído tampoco es motivo para perder
el caso.

### 3.4 `confidence_rationale` se guarda en cualquier desvío del piso, no sólo cuando cambia el número

La redacción literal de la tercera guarda de W2 —`confidence != base_confidence
⟹ hay rationale`— dejaría sin justificar un caso donde el Arbiter escala la
`decision` (de `CHALLENGE` a `BLOCK`, por ejemplo) pero mantiene la misma
`confidence`. ADR-0016 promete algo más fuerte en sus consecuencias: *"cada
desvío del piso queda en `confidence_rationale`"*. El nodo lo implementa así:
guarda el rationale si `decision != piso` **o** `confidence != base`, no sólo
la segunda condición. La guarda de W2 no lo exige —comparar contra eso sería
débil—, pero el nodo lo hace de todos modos porque es lo que el ADR prometió
para el entregable 7.

### 3.5 Por qué no se sella `arbiter_prompt_version` todavía

Mismo patrón que `explanation_prompt_version` sería la extensión obvia — y se
consideró. Se decidió que no, por ahora (decisión del usuario, explícita):
agregar un sexto y séptimo eje de auditoría es una migración y un compromiso
de esquema que conviene resolver cuando haya uso real de esos sellos, no por
simetría con un patrón existente. `GraphContext.judge` ya sigue el mismo
molde perezoso que `narrator`/`embedder`, así que agregar el sello más
adelante no toca la forma del puerto, sólo el nodo y el modelo.

### 3.6 Qué mide DeepEval y qué deliberadamente no

La primera versión de `scripts/eval_golden_set.py` iba a incluir una métrica
de "¿el veredicto respeta el piso?". Se descartó antes de escribir el prompt
del juez: eso ya lo garantiza la cuarta guarda de W2 **estructuralmente** —si
se violara, el caso cae a `FAILED`—, y medir con un LLM lo que el código ya
prueba habría sido peor que no medirlo: dos fuentes de verdad para el mismo
hecho, una determinística y otra no. Las dos métricas que quedaron
—`fundamentacion_del_debate` y `calidad_del_juicio_del_arbiter`— miden algo
que el código estructuralmente no puede: si el argumento inventa evidencia, y
si el rationale de una escalada señala razones concretas o es cautela
genérica.

---

## 4. Convenciones nuevas fijadas

- **Un gate no compara con igualdad estricta contra la salida de un
  componente no determinístico que puede apartarse en una dirección
  conocida.** Compara contra la restricción que el sistema garantiza. Ver
  §2.
- **Un desvío del piso se audita completo, no sólo cuando cambia un número.**
  `decision != piso` es motivo suficiente para justificar, aunque
  `confidence` no se haya movido.
- **Puerto distinto cuando la forma del contrato de salida es distinta**,
  aunque el proveedor de abajo sea el mismo — `Judge` junto a `Narrator`, los
  dos sobre Anthropic.
- **Una dependencia de evaluación (no de producción) vive en un grupo de
  `uv` opt-in**, fuera de `default-groups`, para no inflar el entorno de
  cada `dev sync` con una cadena de paquetes que ningún gate corre.

### Footguns verificados en esta etapa

| Trampa | Detalle |
|---|---|
| `DeepEvalBaseLLM` exige subclase real, no duck typing | `deepeval.metrics.utils.initialize_model` hace `isinstance(model, DeepEvalBaseLLM)`; una clase que sólo implementa el mismo protocolo por estructura falla con `TypeError: Unsupported type for model`. |
| G-Eval trunca el JSON de salida con `max_tokens` bajo | El juez de DeepEval razona paso a paso y devuelve un JSON con score y motivo; con `context` largo (dos argumentos de debate completos) y `max_tokens=1024`, la respuesta se cortaba a mitad del JSON y `trimAndLoadJson` fallaba. Subir a 2048 no lo eliminó del todo (2/7 casos siguieron fallando) — degradado con try/except por caso, no bloquea la corrida. |
| `String(16)` en `issuer_bank` | Un emisor sintético de smoke con nombre descriptivo (`SMOKE-BANK-JUICIO`, 18 caracteres) revienta `TransactionIn` en la validación de Pydantic antes de tocar la base. |
| `uv add --group <nombre>` no es opt-in por defecto | Sin `[tool.uv] default-groups`, un grupo nuevo se sincroniza igual que `dev` — hay que declarar explícitamente qué grupos entran por defecto. |

---

## 5. Verificación de la etapa

| Gate | Resultado |
|---|---|
| `pytest` | 260 verdes, sin red y sin base (235 al cierre de la etapa anterior) |
| `check_policies.py --source=db` | 7 000/7 000, sin cambios respecto de la etapa anterior — `domain/engine.py` no se tocó |
| `smoke_decision.py` | 5 escenarios en `DECIDED`/`PENDING_HUMAN`; el Arbiter LLM no bajó del piso en ninguno |
| `smoke_agents.py` | 60/60 coinciden con el ground truth, Postgres y motor offline |
| `export_data_model_diagram.py --check` | limpio, 14 tablas (sin cambios) |
| `export_graph_diagram.py` | sin cambios — la topología del grafo no se tocó, sólo el cuerpo de los nodos |
| `eval_golden_set.py` (corrida real, no bloqueante) | 7/7 casos evaluados; `fundamentacion_del_debate` 0.2–1.0 (mayormente 0.2–0.5); `calidad_del_juicio_del_arbiter` 0.8 en los 5 casos con desvío del piso, 2 fallos de parseo del juez degradados a "error del juez" |

### La demostración de la capacidad

El escenario 5 de `smoke_decision.py` dispara sólo FP-10 (piso `CHALLENGE`) y
deja `NO_CUSTOMER_PROFILE` como señal aislada — evidencia que el piso no ve
porque ninguna política la reúne, pero que el Arbiter sí, junto con los dos
argumentos de debate. La corrida real mostró al Arbiter razonando
explícitamente sobre esa evidencia y **decidiendo quedarse en el piso**, con
un `confidence_rationale` que explica por qué la evidencia adicional no
alcanzaba para escalar. Es la demostración correcta del rol: el Arbiter
evaluó y decidió, con criterio visible, no que escalara por defecto.

---

## 6. Hallazgos y deuda

### 6.1 El golden set quedó en 7 casos reales, no ~15

El plan de la etapa proponía "~15, estratificados". Se curaron 7 a mano
contra `data/ground_truth.csv` —uno por veredicto, el caso de contradicción
(`FP-02`+`FP-04`), y dos de FP-10— porque siete casos ya alcanzan para
ejercitar de punta a punta el cableado real (grafo, DB, dos proveedores,
juez de DeepEval) y correrlos de verdad tiene costo real en cada sesión.
Ampliar el golden set es trabajo futuro, no bloqueante.

### 6.2 Sin caso de agente degradado en el golden set

El plan mencionaba "un par con agente degradado simulado". No se incluyó:
simular la degradación dentro del golden set requiere un `GraphContext` con
un proveedor roto sólo para esos casos, lo que hace el script más complejo
para un beneficio marginal —la degradación del Arbiter ya está cubierta por
`tests/test_node_arbiter.py`—. Queda como extensión futura.

### 6.3 `fundamentacion_del_debate` dio scores bajos en la corrida real (0.2–0.5 en la mayoría)

No está claro todavía si el criterio de G-Eval es más estricto de lo que el
prompt de debate anticipa —los argumentos elaboran en prosa sobre la
evidencia, y esa elaboración puede leerse como "invención" aunque sea
paráfrasis razonable— o si el prompt necesita ceñirse más a los hechos
entregados. Es exactamente el tipo de hallazgo que ADR-0013 reserva para el
carril de juicio: reporta, no bloquea, y es material real para el entregable
7 (comparación de enfoques y limitaciones identificadas), no algo a
"arreglar" en esta etapa.

### 6.4 `arbiter_prompt_version` / `debate_prompt_version` quedaron deliberadamente afuera

Ver §3.5. Sexto y séptimo eje de auditoría, mismo criterio que
`explanation_prompt_version`, para cuando haya uso real que lo justifique.

### 6.5 El briefing de la etapa anterior seguía nombrando ésta como "próxima etapa"

`docs/briefing_threat_intel.md` no se había retargeteado al cerrar
`feature/threat-intel`. Renombrado y reescrito para apuntar a la etapa
siguiente: `docs/briefing_api_hitl.md`.

### 6.6 Menor

- `2/7` mediciones de `calidad_del_juicio_del_arbiter` fallaron por un JSON
  inválido del juez de DeepEval incluso con `max_tokens=2048`; degradado a
  "error del juez" en vez de abortar la corrida, pero la causa raíz (prompt
  de evaluación largo, sin límite adaptativo) no se investigó a fondo.
- El golden set no se regenera automáticamente si el dataset cambia: es un
  archivo curado a mano, con los `transaction_id` fijos.

---

## 7. Mapa de archivos al cierre

```
src/multiagent_fraud_detection/
├── debate/
│   ├── pro_fraud.py                # SYSTEM_PROMPT, PROMPT_VERSION, build_prompt, fallback_argument
│   └── pro_customer.py             # mismo molde, argumento contrario
├── arbiter/
│   ├── judge.py                    # ArbiterVerdict, Judge, AnthropicJudge, FakeJudge
│   └── prompt.py                   # SYSTEM_PROMPT, PROMPT_VERSION, build_prompt (piso + evidencia + debate)
├── domain/
│   └── params.py                   # + precedencia()
├── explain/
│   └── audit.py                    # + párrafo de debate
└── graph/
    ├── context.py                  # + judge: Judge
    └── nodes.py                    # debate_pro_fraud/pro_customer y decision_arbiter reales; _verificar_invariantes(state, catalog) + cuarta guarda

scripts/
├── smoke_decision.py               # + escenario 5; escenarios 1 y 4 comparan por precedencia, no por igualdad
└── eval_golden_set.py              # golden set + DeepEval, --dry-run, fuera de pytest

data/eval/golden_set_llm_agents.json

tests/
├── test_debate_prompts.py
├── test_node_debate.py
├── test_judge.py
├── test_node_arbiter.py
├── test_citations.py               # + cuarta guarda
└── test_explain.py                 # + párrafo de debate
```

---

## 8. Qué sigue

**Inmediato**: publicar el contrato **v0.9**. Dos enmiendas (cuarta guarda de
W2, corrección de la descripción de `confidence`); sin decisiones conjuntas
pendientes.

**Lo que falta del reto**: API FastAPI + HITL, y CI/imagen/despliegue — las
dos filas `⬜` que quedan en la tabla de estado del README. Con esta etapa
cerrada, los nueve nodos del grafo están todos implementados.

**Deuda declarada para el informe**: scores bajos de `fundamentacion_del_debate`
sin diagnóstico (§6.3), golden set en 7 casos y no ~15 (§6.1), sin caso de
agente degradado en el golden set (§6.2).

---

## 9. Documentación asociada

- `adr/0006-reparto-deterministico-y-llm.md`
- `adr/0013-que-se-mide-con-metricas-duras-y-que-con-llm-as-judge.md`
- `adr/0016-el-arbitro-con-llm-escala-pero-no-cruza-el-piso-determinista.md`
- `enmiendas_pendientes.md` — vacío tras publicar; dos enmiendas hacia v0.9, en `CHANGELOG.md`
- `07-threat-intel.md` — etapa anterior
- `briefing_api_hitl.md` — hacia adelante, para la etapa siguiente
