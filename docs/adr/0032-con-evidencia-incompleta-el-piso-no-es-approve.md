# ADR-0032: con evidencia incompleta, el piso no es APPROVE

- **Estado**: aceptado
- **Fecha**: 2026-10-06
- **Actualiza**: ADR-0016 (el piso pasa de `prescribed_action` a `piso_efectivo`)
  y ADR-0031 (resuelve su "No se resuelve").

## Contexto

ADR-0031 dejó abierto que, en los casos de borde, el árbitro con LLM no es
determinístico. No se puede fijar la temperatura (Sonnet 5 rechaza valores
distintos del default), y el razonamiento adaptativo toma caminos distintos en
cada corrida. Se midió con 12 casos de borde × 5 corridas, construidos como los
produciría el grafo: si cae un agente o falta el perfil, desaparecen sus señales
y sus políticas, y el debate se regenera sobre lo que quedó.

| Situación | Antes |
|---|---|
| **Agentes de señales caídos** (4 casos con la misma evidencia: ninguna señal, ninguna política) | Uno aprobaba siempre; dos pedían verificación siempre; el cuarto variaba. El veredicto dependía de cómo quedó redactado el debate |
| Cliente sin perfil, con la señal real (`NO_CUSTOMER_PROFILE`, severidad media) | APPROVE en 20 de 20: el árbitro ya respeta el diseño |
| Argumento del debate que afirma hechos que no están en la evidencia | 2 casos con 4 a 1 |

9 de las 11 políticas dependen de `behavioral_pattern`. Si ese agente cae,
"ninguna política disparó" puede significar "no se pudo evaluar casi ninguna", y
el piso igual era APPROVE.

En la escalada real de producción el árbitro escaló porque el RAG estaba caído y
supuso que las políticas podían estar incompletas. Es falso: las políticas que
disparan las decide el motor, y la cita se resuelve por identidad, sin el índice
(ADR-0011).

## Decisión

1. **`piso_efectivo(catalog, matched_policies, degraded_agents)`** en
   `domain/engine.py`: es `prescribed_action`, pero si cayó un agente que produce
   señales (`transaction_context`, `behavioral_pattern`, `external_threat_intel`)
   y el piso es APPROVE, sube a **CHALLENGE**. Si ya era más cauteloso, no cambia.
   `internal_policy_rag` no cuenta (ADR-0011).

   **CHALLENGE y no ESCALATE_TO_HUMAN:** verificar con el cliente es proporcional
   a "no pude evaluar todo"; la cola humana queda para la evidencia
   contradictoria. El árbitro puede seguir subiendo el piso.

2. **Una sola función para el árbitro y la cuarta guarda** de `persist_decision`.
   Si cada uno calculara el piso por su lado, la guarda podría rechazar lo que el
   árbitro decidió. `prescribed_action` sigue siendo la línea base del harness y
   del gate 7000/7000, que corre sin agentes caídos y no cambia.

3. **El prompt del árbitro** (`arbiter-verdict:3`) agrega dos reglas y quita una
   mención:
   - los argumentos del debate interpretan la evidencia, no la amplían: un hecho
     que no figura entre las señales no cuenta;
   - un agente de señales caído ya elevó el piso, y no hace falta volver a
     escalar sólo por eso; un RAG caído no deja incompletas las políticas que
     dispararon;
   - la regla 3 deja de nombrar "un agente degradado" como motivo para escalar.

4. **La explicación de auditoría** dice cuándo el piso no pudo ser APPROVE por un
   agente de señales caído.

## Alternativas descartadas

**Una regla para "cliente sin perfil".** Contradice el diseño (`evidence_aggregation`:
"no pude evaluar no es esto es sospechoso") y el ground truth (84 de las 96
transacciones sin perfil son APPROVE), y rompería el gate. Con la señal real, el
árbitro ya aprueba 20 de 20. Las escaladas que motivaron la idea venían de un caso
construido que exageraba la señal (severidad alta y otro texto).

**Subir a ESCALATE_TO_HUMAN.** Manda a la cola humana algo que una verificación
con el cliente resuelve, y la llena justo cuando el sistema está degradado.

**Temperatura 0 o varias corridas con votación.** La temperatura no se puede fijar
en este modelo, y votar multiplica el costo de cada decisión para resolver lo que
una regla resuelve sin LLM.

## Consecuencias

Medido con los mismos 12 estados × 5 corridas:

| | Antes | Después |
|---|---|---|
| Estados con veredicto estable (5 de 5) | 9/12 | **11/12** |
| Agentes de señales caídos | mixto; un caso aprobaba siempre | **CHALLENGE 20/20**, por regla |
| Sin perfil | APPROVE 20/20 | APPROVE 20/20 |
| Argumento fuerte sin evidencia | 2 casos con variación | 1 corrida de 20 que escala |

En 20 casos reales de producción, 19 iguales. El que cambió es la escalada real,
que pasó de CHALLENGE a APPROVE: escalaba por el RAG caído, con la premisa falsa
que corrige este ADR. El ground truth de ese escenario es APPROVE.

**Se paga**: con un agente de señales caído, una transacción legítima pasa por una
verificación con el cliente. Es el costo de no aprobar sin haber evaluado.

**Queda**: un margen de variación del LLM en los casos genuinamente ambiguos (1 de
60 corridas), siempre por encima del piso.
