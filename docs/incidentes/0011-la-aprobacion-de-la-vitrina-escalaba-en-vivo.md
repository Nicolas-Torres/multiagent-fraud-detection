# Incidente 0011 — la aprobación de la vitrina escalaba al re-ejecutarla

**Fecha**: 2026-09-30. **Detectado**: en la revisión del dashboard antes de
publicar, al re-ejecutar la fila "Aprobación limpia" de la vitrina. No hubo
alerta del sistema.
**Impacto**: en las dos demos, la vitrina muestra T-2579 como "Aprobado", pero
cada corrida en vivo de esa misma fila terminaba "Derivado al analista". Un
visitante lee que el sistema no es reproducible.

## Síntoma

Todas las corridas `LIVE-t2579-…` salieron `ESCALATE_TO_HUMAN` con FP-02 y las
señales `FOREIGN_COUNTRY` y `NEW_DEVICE`. El caso original aprobó con una sola
señal, `FOREIGN_COUNTRY`.

## Causa raíz

La misma del incidente 0008, por otro camino. `transaccionParaCorridaEnVivo`
sufija `device_id` y `merchant_id` en cada corrida. FP-02 es
`country_not_usual() ∧ device_not_usual()`. T-2579 es de CU-0643, cuyo país
habitual es ES, pagando desde PE con su dispositivo habitual: la mitad de FP-02
ya estaba presente. El sufijo vuelve nuevo al dispositivo y completa la
conjunción.

El filtro del incidente 0008 (`NO_SOBREVIVEN_AL_SUFIJO`) mira las políticas que
**disparan** en la fila. Acá el problema es una política que **no** dispara en
la fila y sí en vivo, y la vitrina nunca pasó por ese filtro: la eligió
`seed_showcase.py` a mano.

## Fix

- La aprobación de la vitrina pasa a ser **T-1031** (CU-0115, 4 941,30 PEN,
  web, desde PE, dentro de su horario). Sin ninguna señal en la fila; en vivo,
  sólo `NEW_DEVICE`, que por sí sola no activa ninguna política.
- `CASOS_VITRINA` y `showcase_cases.json` actualizados.
- CU-0115 entra en `CLIENTES_EN_USO` de `seed_diverse_scenarios.py`. CU-0643 se
  queda: su fila sigue sembrada en las bases desplegadas.
- `tests/test_showcase_live.py`: cada caso de la vitrina, corrido tres veces en
  vivo sobre el historial que deja la fila original, llega a la acción de su
  *ground truth*. Con T-2579 falla y lo nombra; los otros cuatro pasan.

Los cooldowns guardados en el `localStorage` bajo `t2579` quedan inertes: ya
no hay fila que los lea.

## Aprendizaje

La condición no es "qué políticas disparan en la fila", sino "la corrida en
vivo llega al mismo veredicto que la fila". Lo segundo se prueba directo con el
motor, sin enumerar qué políticas son frágiles.
