# Incidente 0008 — el escenario "Comercio con historial de fraude" aprobaba

**Fecha**: 2026-09-26. **Detectado**: en la prueba de carga previa a publicar
las demos, al comparar cada veredicto con la señal que promete su fila. No hubo
alerta del sistema.
**Impacto**: en las dos demos, la fila "Comercio con historial de fraude" (`t1249`)
terminaba en `APPROVE`. Un visitante que la ejecuta ve que el sistema aprueba
justo el caso que la etiqueta presenta como sospechoso, y lo lee como un error
del motor.

## Síntoma

`LIVE-t1249-…` salió `APPROVE` en Azure y en GCP, con `matched_policies: []` y
una sola señal (`NEW_DEVICE`). La etiqueta de la fila promete FP-07.

## Causa raíz

`transaccionParaCorridaEnVivo` (`dashboard/src/data/liveScenarios.ts`) sufija
`device_id` y `merchant_id` en cada corrida (`M-999` → `M-999-<token>`). Es a
propósito: sin el sufijo, las corridas de distintos visitantes se acumulan sobre
el mismo dispositivo y el mismo comercio en la misma ventana fija, y FP-03 y
FP-11 empiezan a disparar por evidencia que genera el propio uso de la demo.

Ese razonamiento se verificó para los tres escenarios escritos a mano, cuya
señal no depende del dispositivo ni del comercio. Después,
`seed_diverse_scenarios.py` sumó escenarios elegidos del *ground truth* sin ese
filtro, y `t1249` depende exactamente de la identidad del comercio: FP-07 es
`merchant_blacklisted() ∧ amount_over_absolute(135)`. `M-999-<token>` no está
en la lista negra, así que la política nunca aplica.

Tres políticas no sobreviven al sufijo:

| Política | Depende de |
|---|---|
| FP-03 | la historia del **dispositivo** |
| FP-07 | la **identidad** del comercio (lista negra) |
| FP-11 | la historia del **comercio** en el día |

## Por qué no se quita el sufijo para `t1249`

FP-11 cuenta los cargos del mismo cliente al mismo comercio en el día local, y
el timestamp del escenario es fijo (ADR-0004). Sin el sufijo, cada corrida suma
un cargo más de CU-0038 a M-999 ese mismo día y, con el uso, el escenario deriva
hacia `BLOCK`: el mismo problema que el sufijo existe para evitar.

## Fix

`seed_diverse_scenarios.py` descarta los candidatos cuya señal depende del
dispositivo o del comercio (FP-03, FP-07, FP-11), y `diverse_scenarios.json` se
regenera: `t1249` se reemplaza por otro caso `ESCALATE_TO_HUMAN` cuya señal sí
sobrevive al sufijo.

Se pierde la fila que mostraba la lista negra de comercios en vivo. Es el costo
de que cada fila ejecutable cumpla lo que promete.

## Verificación

*(pendiente: se completa con el PR)*

## Aprendizaje

Una transformación verificada contra un conjunto de casos no se hereda a los
casos que se suman después. La condición ("la señal no depende del dispositivo
ni del comercio") tenía que vivir en el código que elige los escenarios, no en
un comentario sobre los tres primeros.
