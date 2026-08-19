# ADR-0018: el progreso del análisis se transmite por SSE, no por WebSocket

- **Estado**: aceptado
- **Fecha**: 2026-08-19

## Contexto

La vista de demo del dashboard (`Home.tsx`, panel fijo con casos en vivo)
tiene que mostrar el grafo de agentes corriendo, no sólo el veredicto final.
Hasta esta etapa no había forma honesta de hacerlo: W2 escribe la decisión
completa en un solo commit, sin estados intermedios persistidos (§7.3 del
contrato — "un reintento sustituye, no complementa"), así que el polling
sobre `GET /cases/{id}` no tiene nada que mostrar hasta que el caso ya
terminó. La única alternativa disponible era una animación indeterminada
—un barrido visual sin lectura de estado real—, que quedó documentada como
tal, pero no es progreso real.

Esto no es una necesidad nueva: el contrato ya la anticipó — **§5, decisión
3**: *"Notificación al dashboard: Polling en v1; WebSocket = mejora
(entregable 10)"*. Esta etapa implementa esa mejora ya prevista.

## Decisión

**El backend expone `GET /api/v1/cases/{case_id}/stream` por Server-Sent
Events (SSE)**, no por WebSocket. El nodo que termina cada paso del grafo se
publica a un registro en memoria (`dict[case_id, list[Queue]]`), alimentado
al cambiar el punto de invocación del grafo de `ainvoke()` a
`astream(stream_mode="updates")` — el resto de la ejecución no cambia. El
canal es puramente efímero: nunca escribe a Postgres, nunca reemplaza al
polling, que sigue siendo la única fuente de verdad del veredicto final.

## Alternativas descartadas

**WebSocket real, la palabra que el contrato ya tenía escrita.** El caso de
uso es estrictamente unidireccional: el servidor informa qué nodo terminó,
el cliente nunca manda nada de vuelta. Un canal bidireccional sería
complejidad sin necesidad, y exige más cuidado de infraestructura (afinidad
de conexión, proxies, balanceadores) en una etapa de despliegue que todavía
no existe. SSE corre sobre HTTP plano y el navegador reconecta solo vía
`EventSource` nativo, sin librería nueva en ningún lado.

**Persistir los pasos intermedios en `cases`/`decisions` para que el
polling los vea.** Rompería la garantía central de W2 —"el resultado de
este nodo para este caso es exactamente esto, no *asegurate de que estas
filas existan*"— que existe justamente para que un reintento sustituya en
vez de acumular. Convertir eso en un modelo con estados a medias visibles es
exactamente lo que esa garantía se diseñó para evitar.

**Quedarse sólo con la animación indeterminada.** Cumplía el mínimo —no
mentía sobre lo que sabía— pero no es lo que se pidió, y ya era la opción
por defecto antes de esta etapa: no hay nada nuevo que decidir ahí.

## Consecuencias

**Se gana** progreso real y verificable en la demo, sin tocar la atomicidad
de la auditoría persistida: el stream es un canal secundario y efímero,
nunca la fuente de verdad.

**Se paga**: una superficie de API que no estaba en el contrato hasta ahora
(entra por enmienda, no por versión publicada todavía). En despliegue, un
proxy reverso típico necesita `proxy_buffering off` (o el equivalente del
proveedor) para no bufferear una respuesta `text/event-stream` — queda
anotado para cuando exista la etapa de CI/despliegue, no se resuelve acá.
Si el proceso reinicia a mitad de una corrida el stream se corta sin aviso
—el caso igual termina bien, por polling—, deuda aceptada y declarada, no
un olvido.
