# Evaluación: consistencia del árbitro en los casos de borde

> Fecha: 2026-10-06. Respalda [ADR-0032](../adr/0032-con-evidencia-incompleta-el-piso-no-es-approve.md).

## La pregunta

¿El árbitro da el mismo veredicto si se le muestra el mismo caso dos veces? En los
casos simples, sí: en producción confirma el piso siempre. En los casos de borde,
no siempre. No se puede fijar la temperatura (Sonnet 5 rechaza valores distintos
del default), y el razonamiento adaptativo toma caminos distintos en cada corrida.

## Cómo se midió

Cuatro casos reales de producción, con tres variantes cada uno, construidas como
las produciría el grafo:

| Variante | Qué cambia en el caso |
|---|---|
| Agentes de señales caídos | Caen `behavioral_pattern` y `external_threat_intel`: desaparecen sus señales y sus políticas, el piso se recalcula, y el debate se regenera sobre lo que quedó |
| Cliente sin perfil | Desaparecen las señales y políticas que necesitan perfil, y aparece `NO_CUSTOMER_PROFILE` tal como la emite producción (severidad media) |
| Argumento fuerte | El argumento del debate afirma hechos que no figuran entre las señales |

12 estados, **5 corridas cada uno**, antes y después del cambio. Los estados se
construyeron una vez y se reutilizaron: antes y después vieron exactamente la
misma evidencia y los mismos argumentos.

## Resultados

| | Antes (`arbiter-verdict:2`) | Después (`arbiter-verdict:3` + `piso_efectivo`) |
|---|---|---|
| Estados con veredicto estable (5 de 5) | 9/12 | **11/12** |
| Agentes de señales caídos | Un caso **aprobaba siempre**, dos pedían verificación siempre, uno variaba | **CHALLENGE 20/20**, por regla |
| Cliente sin perfil | APPROVE 20/20 | APPROVE 20/20 |
| Argumento fuerte | 2 casos con 4 a 1 | 1 corrida de 20 que escala |

**Lo que mostró el "antes":**

- Con un agente de señales caído, los cuatro casos tenían **la misma evidencia**
  (ninguna señal, ninguna política). Aun así el veredicto cambiaba según cómo
  quedara redactado el debate. Con 9 de las 11 políticas dependiendo de
  `behavioral_pattern`, aprobar ahí era aprobar sin haber evaluado.
- "Sin perfil" no era un problema: con la señal real, el árbitro ya respetaba el
  diseño ("no pude evaluar no es esto es sospechoso"). Una medición anterior, con
  una señal exagerada, había sugerido lo contrario.

**Casos reales:** en 20 casos de producción, 19 dieron igual. Cambió la escalada
real, que pasó de CHALLENGE a APPROVE: escalaba porque suponía que con el RAG caído
las políticas podían estar incompletas, y no es así (ADR-0011). El ground truth de
ese escenario es APPROVE.

## Lo que queda

Una corrida de 60 que escala en un caso genuinamente ambiguo, siempre por encima
del piso. Para eliminarla del todo habría que votar entre varias corridas, y eso
multiplica el costo de cada decisión.

## Lección

**Medir un LLM con una sola corrida da ruido.** Las comparaciones de un caso o dos
(Jev, Sonnet 5.5) son indicativas, no concluyentes. Las conclusiones que se
sostienen son las de diferencias grandes (Jev: 8 escaladas omitidas de 8) o
medidas con varias corridas.
