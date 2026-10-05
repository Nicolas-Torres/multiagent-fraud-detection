# ADR-0031: el modo de razonamiento es explícito y el tope de tokens lo cubre

- **Estado**: aceptado
- **Fecha**: 2026-10-05
- **Actualiza**: ADR-0026 (el debate pasa de 400 a 600 tokens; cada llamada,
  además de su modelo, declara su modo de razonamiento).

## Contexto

`claude-sonnet-5` razona internamente (*adaptive thinking*) por defecto, y ese
razonamiento **cuenta dentro de `max_tokens`**. Ningún nodo lo configuraba: el
comportamiento dependía del default del proveedor.

Lo encontró la prueba en sombra de Jev, al pedirle a Sonnet una referencia sobre
casos difíciles construidos (un agente de evidencia caído, un cliente sin perfil):

- **Árbitro (tope 500):** razonó 334 tokens y el JSON del veredicto quedó cortado
  (`stop_reason: max_tokens`). Con 2 000 de tope, 9 de los 12 casos difíciles
  usaron más de 500 (de 579 a 950). En producción, el nodo habría degradado: el
  caso pasaba a ESCALATE_TO_HUMAN con "proveedor de juicio no disponible",
  aunque Sonnet quisiera aprobar.
- **Explicación al cliente (tope 400):** la de un BLOCK razonó 306 tokens y llegó a
  425. El narrador tomaba los bloques de texto **sin mirar si la respuesta había
  terminado**: un texto cortado se habría guardado como si estuviera completo.
- **Debate (tope 400):** no razonó ni en los casos difíciles, pero en producción
  un argumento llegó a 343 tokens (86 % del tope).

En producción no pasó: en LangSmith (30 días), las 108 llamadas del árbitro y las
del debate y la explicación terminaron con `end_turn`, sin razonamiento. Los
casos de la demo son simples. Por eso no es un incidente, sino un defecto latente:
aparece justo en los casos difíciles, que es donde el árbitro tiene que aportar.

Medición (`docs/temp/token-budget/`): sin razonamiento, el árbitro **omitió 3 de
las 7 escaladas** que hace con razonamiento.

## Decisión

1. **El modo de razonamiento es un parámetro de generación, como el modelo:** se
   declara en código, junto a `MODEL`, y viaja explícito en cada llamada.

   | Nodo | Razonamiento | Tope | Antes |
   |---|---|---|---|
   | `decision_arbiter` | `adaptive` | 2 000 | default implícito, 500 |
   | `debate_pro_fraud` / `debate_pro_customer` | `disabled` | 600 | default implícito, 400 |
   | `explainability` (cliente) | `disabled` | 400 | default implícito, 400 |

   El árbitro razona porque su tarea es juicio bajo evidencia contradictoria. El
   debate y la explicación redactan prosa a partir de evidencia ya resuelta: no
   lo necesitan, y sin razonamiento el tope es predecible.

2. **Una respuesta que no terminó no se usa.** Si `stop_reason` no es `end_turn`
   (`max_tokens`, `refusal`), el árbitro levanta `JudgeError` y el narrador
   `NarrationError`, con el motivo en el mensaje. Cada nodo ya tiene su camino de
   degradación: el árbitro escala con el piso, el debate usa su argumento de
   respaldo, la explicación usa la plantilla.

3. **El árbitro valida fuera del SDK.** `messages.parse` validaba el JSON adentro y
   fallaba antes de que se pudiera mirar `stop_reason`. Ahora usa
   `messages.create` con el mismo esquema (`transform_schema`) y valida con
   `ArbiterVerdict` después. Al usar `create`, `wrap_anthropic` lo traza con
   tokens y costo, igual que al narrador, y el `traceable` manual sobra.

4. **Las generaciones suben:** `arbiter-verdict:2`, `debate-pro-fraud:2`,
   `debate-pro-customer:2` y `customer:2`. La explicación al cliente es la única
   sellada en la decisión (`explanation_prompt_version`): las decisiones nuevas
   dicen `claude-sonnet-5:customer:2`; las anteriores conservan su sello.

El texto de la razón degradada del árbitro ("proveedor de juicio no disponible…")
no cambia: el incidente 0003 lo usa como marca para encontrar decisiones
contaminadas. La causa precisa queda en `agent_errors` (por ejemplo,
`stop_reason=max_tokens`).

## Alternativas descartadas

**Sin razonamiento también en el árbitro.** Más barato y con tope predecible,
pero omitió 3 de 7 escaladas en los casos difíciles.

**Presupuesto fijo de razonamiento** (`enabled` con `budget_tokens`). Sonnet 5.5
ya no lo acepta, y el adaptativo no gasta nada en los casos simples (0 de 40 en
producción).

**Migrar a `claude-sonnet-5-5`.** Evaluado sobre los mismos casos
(`docs/temp/token-budget/evaluacion-sonnet-5-5.md`): decide igual (20/20 en
producción, 7/7 escaladas difíciles), pero no fue más rápido (árbitro 4,0 s
contra 3,8 s) ni más barato, y en un caso tomó por evidencia lo que afirmaba un
argumento del debate. `claude-sonnet-5` sigue activo hasta, como mínimo, el
30/06/2027. En 5.5, `disabled` da error 400: el reemplazo es `between_tools`. Un
test exige revisar el modo si cambia el modelo.

## Consecuencias

**Se gana**: el árbitro resuelve los casos difíciles en vez de degradar; ningún
texto cortado llega a la base; el comportamiento no depende del default del
proveedor.

**Se paga**: en los casos difíciles el árbitro gasta más (hasta ~950 tokens de
salida en vez de ~260) y tarda más (de 4 a 13 s en los 12 casos medidos, contra
~4 s). Los casos simples no cambian.

**No se resuelve**: en los casos difíciles el árbitro **no es determinístico**.
Con la misma configuración, dos corridas de los 12 casos coincidieron en 10: un
caso "sin perfil" escaló en una y aprobó en la otra, y un caso con agentes caídos
se quedó en el piso en una y escaló en la otra. Las dos situaciones que motivan
casi todas sus escaladas (un agente de evidencia caído, un cliente sin perfil)
son determinísticas: como reglas del piso, no dependerían de esa variación. Queda
como propuesta para otro ADR.

**Verificado** (2026-10-05):

- Contra la API real, el caso difícil que antes cortaba el veredicto resolvió
  ESCALATE_TO_HUMAN, como la referencia.
- Los 12 casos difíciles con la configuración final: 0 cortes.
- `tests/test_llm_token_budget.py`: sin el chequeo de `stop_reason`, los cuatro
  casos de corte fallan.
