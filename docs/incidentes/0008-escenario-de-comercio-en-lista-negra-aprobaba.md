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

## Hallazgo relacionado: la etiqueta de FP-02

Al revisar los escenarios apareció el mismo defecto en el texto:
`POLITICA_A_FRASE` describía FP-02 como *"canal nuevo con monto alto"*, pero
FP-02 es `country_not_usual() ∧ device_not_usual()`: una compra internacional
desde un dispositivo nuevo. La fila `t1026` prometía una señal que no es la que
evalúa el motor.

## Fix

Commit `5adfdd9`, rama `fix/provider-client-race-and-live-scenarios`:

- `seed_diverse_scenarios.py` descarta los candidatos con FP-03, FP-07 o FP-11
  (`NO_SOBREVIVEN_AL_SUFIJO`).
- FP-02 pasa a describirse como *"compra internacional desde un dispositivo
  nuevo"*.
- `diverse_scenarios.json` regenerado: `t1249` sale y entra `t1155` (FP-08,
  cuenta nueva con un monto grande, `ESCALATE_TO_HUMAN`). Los otros cinco
  escenarios no cambian. Sólo cambia la etiqueta de `t1026`.
- `tests/test_diverse_scenarios.py`:
  - Ningún escenario elegido depende del dispositivo o del comercio. El
    conjunto se declara en el test, no se importa del script, para que vaciar
    la constante no lo deje pasando.
  - El JSON comprometido es exactamente el que genera el selector.

Se pierde la fila que mostraba en vivo la lista negra de comercios. Es el costo
de que cada fila ejecutable cumpla lo que promete.

Los IDs de `t1249` guardados en el `localStorage` de los visitantes quedan
inertes: sólo los lee su propia fila, que ya no existe.

## Verificación

- **Sin el filtro, los dos tests fallan** y nombran `t1249` con `['FP-07']`.
  Con el filtro, pasan.
- `pytest` completo, `ruff`, `tsc` y el build del dashboard en verde.
- **Después del deploy** ([PR #59](https://github.com/Nicolas-Torres/multiagent-fraud-detection/pull/59),
  `sha-904b426`, GCP): `t1155` dio `ESCALATE_TO_HUMAN` con `FP-08`, y `t1026`
  dio `ESCALATE_TO_HUMAN` con `FP-02` (señales `FOREIGN_COUNTRY` y
  `NEW_DEVICE`). Las dos coinciden con su fila.

## Aprendizaje

Una transformación verificada contra un conjunto de casos no se hereda a los
casos que se suman después. La condición ("la señal no depende del dispositivo
ni del comercio") tenía que vivir en el código que elige los escenarios, no en
un comentario sobre los tres primeros.
