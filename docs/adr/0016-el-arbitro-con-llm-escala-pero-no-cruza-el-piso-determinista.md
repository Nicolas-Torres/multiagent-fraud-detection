# ADR-0016: el Arbiter con LLM escala, pero no cruza el piso determinista

- **Estado**: aceptado
- **Fecha**: 2026-08-06

## Contexto

`decision_arbiter` existe hoy como stub determinista, y lo dice de sí mismo en
su propio docstring: *"No es el Arbiter final [...] El Arbiter con LLM lo
reemplaza y puede apartarse con justificación auditable."* [ADR-0006](0006-reparto-deterministico-y-llm.md)
ya le asignó el rol —*"juicio bajo evidencia contradictoria"*— pero no dijo
qué puede cambiar ni hasta dónde. Falta cerrar eso antes de escribir el nodo.

El esquema ya trae el mecanismo listo, sin que nada lo llene todavía:
`base_confidence` (determinista) + `confidence` (ajustable, acotado) +
`confidence_rationale` (obligatorio si difieren). Se construyó para esto en la
etapa del grafo, dos etapas antes de que hubiera un Arbiter capaz de usarlo.

Y queda una pregunta que v0.7 dejó explícitamente afuera. El invariante de
citación —*"si una política disparó, tiene que estar citada"*— es de
**contención**, no de igualdad: no dice nada sobre si el Arbiter puede
apartarse del veredicto que la precedencia prescribe, en cualquier dirección.
El contrato lo nombró y lo difirió: *"Queda fuera deliberadamente la cláusula
recíproca [...] convertiría en error el override pro-cliente que un Arbiter
con LLM podría querer hacer con justificación. Se decide en la rama del
Arbiter."* Esta es esa rama.

## Decisión

**El Arbiter con LLM puede volverse más cauteloso que la precedencia
determinista, nunca menos.**

`prescribed_action(catalog, matched_policies)` —el cálculo que ya vive en
`domain/engine.py`, sin cambios— deja de ser el veredicto final y pasa a ser
el **piso**. El Arbiter LLM elige la `decision` final con la restricción:

> `precedencia(decision) >= precedencia(prescribed_action(...))`

en la escala `BLOCK > ESCALATE_TO_HUMAN > CHALLENGE > APPROVE`. Puede subir de
nivel con justificación; no puede bajar uno que una política ya ganó.

**Qué ve el Arbiter que el piso no ve.** `prescribed_action` es ciego a todo
lo que no sea `matched_policies`: una política es una conjunción completa, y
una señal que la conjunción no cierra —el caso de `NO_CUSTOMER_PROFILE`, o
cualquier señal aislada que el motor ya emite pero ninguna política reúne— no
mueve el piso. El Arbiter LLM sí la ve, junto con los dos argumentos de debate
y `agent_errors` (evidencia degradada). Ahí vive el "juicio bajo evidencia
contradictoria" que ADR-0006 prometió: puede escalar un caso que el piso
manda a `APPROVE` porque el debate expone una contradicción que ninguna
política formaliza todavía.

**Qué sigue intacto.**

- `risk_score` no es ajustable — ya lo fijó ADR-0006, por el mismo motivo:
  si un LLM pudiera moverlo, dejaría de servir para vigilar drift.
- El invariante de contención de §2.5 no cambia: toda política disparada sigue
  citada. El piso es una restricción **nueva y adicional**, no un reemplazo.
- `confidence` se ajusta dentro del mecanismo que ya existe, con
  `confidence_rationale` obligatorio cuando difiere de `base_confidence`.

**Hace falta una cuarta guarda en W2.** Las tres guardas actuales no impiden
estructuralmente que una `decision` quede por debajo del piso —piden citación
y `base_confidence`, no comparan `decision` contra `prescribed_action`—. Se
agrega: `decision != ESCALATE_TO_HUMAN` (exenta, como las otras tres) ⟹
`precedencia(decision) >= precedencia(prescribed_action(catalog,
matched_policies))`. Se implementa cuando se escriba el nodo, no en este ADR.

## Alternativas descartadas

**Override bidireccional con justificación.** Le daría al Arbiter la misma
libertad para bajar que para subir, y es la lectura más "agéntica" del rol.
Se descarta porque reabre exactamente el caso que la contención de §2.5 existe
para cerrar: un auditor preguntando *"¿por qué se aprobó si FP-03 disparó?"*
sin más respuesta que *"el modelo lo consideró razonable"*. Es también la
peor apuesta de cara a la rúbrica: el ítem 7 pide *"comparación de enfoques
**y** limitaciones identificadas"*, no solo comparación, y un piso estricto es
una limitación argumentable; un override sin piso es una capacidad difícil de
defender por escrito si algo sale mal.

**El Arbiter LLM solo ajusta `confidence`, nunca `decision`.** Vaciaría el rol
que ADR-0006 ya le asignó. Si el Arbiter nunca puede escalar un caso más allá
de lo que el piso ya prescribe, "juicio bajo evidencia contradictoria" es
retórica sin efecto observable, y la comparación de enfoques del entregable 7
no tendría nada que comparar del lado del veredicto — solo de la confianza.

**Escalar cuando la confianza cae bajo un umbral.** Ya descartada en
[ADR-0015](0015-la-evidencia-externa-entra-al-veredicto-por-el-vocabulario-del-catalogo.md)
por el mismo motivo, reafirmado acá: el veredicto no sale de umbralizar un
score, y `base_confidence` mide ambigüedad, no riesgo — un 0.50 dice *"no
estoy seguro"*, no *"hay que escalar"*.

## Consecuencias

**Se gana** un Arbiter cuyo único efecto observable y auditable es *más*
cautela, nunca menos: cada desvío del piso queda en `confidence_rationale`, y
el peor caso de un Arbiter que se equivoca es un caso escalado de más, no uno
aprobado de menos.

**Se gana** contenido real para el entregable 7: la comparación "qué hizo el
LLM que el piso determinista no hizo" tiene una métrica concreta —cuántos
casos subieron de nivel, y si esas subidas coinciden con lo que el ground
truth hubiera esperado en los casos donde hay etiqueta (recordando que FP-10
no la tiene, [ADR-0015](0015-la-evidencia-externa-entra-al-veredicto-por-el-vocabulario-del-catalogo.md)).

**Se paga** que el Arbiter es menos "agéntico" de lo que la palabra sugiere,
otra vez — mismo costo de rúbrica que ADR-0006 ya asumió y que hay que seguir
argumentando explícitamente en el informe, no dejarlo implícito en el código.

**Se paga** una guarda nueva en el camino crítico de W2, y con ella un caso de
falla nuevo: un Arbiter que devuelve una `decision` por debajo del piso pasa a
`FAILED` en vez de `DECIDED`. Es el comportamiento correcto —la guarda está
para eso— pero es superficie de error que no existía.

**Sigue pendiente, y no lo resuelve este ADR**: el *golden set* contra el que
se mide la calidad del juicio del Arbiter (DeepEval) es deuda ya declarada por
[ADR-0013](0013-que-se-mide-con-metricas-duras-y-que-con-llm-as-judge.md),
*"de la etapa de agentes con LLM, no de esta"*. Esa etapa es esta. Curar el
golden set queda como tarea de implementación, no como decisión de diseño: la
pregunta de diseño —¿qué gate corre sobre las 7 000 y qué gate corre sobre el
golden set?— ya la resolvió ADR-0013 (capa 2 vs capa 3) y no cambia acá. Las 7
000 siguen midiendo `domain/engine.py` sin tocar; el Arbiter LLM se mide
aparte.
