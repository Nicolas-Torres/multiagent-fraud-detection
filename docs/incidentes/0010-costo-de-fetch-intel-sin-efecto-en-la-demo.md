# Incidente 0010 — `fetch-intel` costaba ~USD 1.1 por día sin efecto en la demo

**Fecha**: 2026-09-26. **No es un incidente de seguridad ni de disponibilidad**:
es una investigación de costo a pedido del usuario, igual que el
[0004](0004-costo-elevado-de-claude-sonnet-4-6-por-max-uses.md).

## Síntoma

El usuario notó que sus créditos de Anthropic bajaban sin tráfico en la demo. La
consola mostraba, para el 26/09, USD 1.02 de `claude-sonnet-4-6` y USD 0.15 de
búsqueda web. Sonnet 4.6 sólo lo usa `fetch-intel`, que corre una vez por día
(06:00 UTC, en Azure; el cron de GCP nunca ejecutó, ver el 0004).

## Medición

Los mismos 7 días en LangSmith:

| Llamada | n | Entrada media | Salida media | Cortadas por `max_tokens` |
|---|---|---|---|---|
| `fetch-intel` (Sonnet 4.6, tope 1024) | 105 | 15 304 | 1 205 | 100 |

Son 15 búsquedas por ejecución, una por emisor, a unos USD 0.074 cada una:

- **Entrada, ~62 %.** La herramienta de búsqueda le devuelve al modelo el
  contenido de unos 10 resultados para que redacte.
- **Salida, ~25 %.** Un informe en markdown con recomendaciones (la traza
  `01a0dc50…` lo muestra) que `searcher._extraer` descarta entero: sólo guarda
  URL, título y fecha, de los bloques de resultado.
- **Búsqueda web, ~13 %.** El modelo además intentaba una segunda búsqueda, que
  fallaba por `max_uses_exceeded`.

El 0004 bajó `MAX_USES` de 3 a 1, pero no tocó la entrada ni la prosa.

## Por qué no aportaba nada a la demo

Ninguna de las 54 decisiones en producción tiene `citations_external` ni FP-10.
FP-10 busca alertas de las 24 h previas al timestamp de la transacción
(*as-of*, ADR-0004), y los escenarios de la demo tienen fechas fijas de diciembre
de 2025. Una alerta recogida hoy nunca cae en esa ventana.

## Fix

[ADR-0026](../adr/0026-cada-llamada-a-un-llm-usa-el-modelo-mas-chico-que-alcanza.md):

- Haiku 4.5 en lugar de Sonnet 4.6.
- Un prompt de sistema que pide una sola búsqueda y ninguna prosa.
- `max_tokens` de 1024 a 100.
- Cadencia semanal.

## Verificación

- **Antes de implementar**, dos llamadas reales con Haiku 4.5:
  - una búsqueda y 10 resultados en cada una;
  - la entrada baja de ~15 300 a ~9 200 tokens;
  - con tope 100, la salida baja de ~1 200 a ~170 tokens, con los resultados
    intactos.

  Costo estimado: ~USD 0.02 por búsqueda.
- **Después del deploy** ([PR #61](https://github.com/Nicolas-Torres/multiagent-fraud-detection/pull/61),
  `sha-954de16`):
  - Cron semanal (`0 6 * * 1`) aplicado por CLI en Azure y GCP. Terraform ya
    tiene el mismo valor, pero `apply` necesita `infra/shared.secrets.tfvars`,
    que no estaba disponible.
  - `fetch-intel` ejecutado a mano en Azure: 15 llamadas con Haiku 4.5, con
    8 093 tokens de entrada y 166 de salida de media. Se cortaron las 15, pero
    el corte cae sobre la prosa. LangSmith calcula USD 0.134 en tokens; con las
    15 búsquedas, unos **USD 0.28 por ejecución (antes ~USD 1.17)**. Con la
    cadencia semanal, de ~USD 35 a ~USD 1.2 al mes.
  - Corpus v2: 5 filas guardadas y 135 descartadas por fecha no reconocible
    (ver el hallazgo lateral).
  - La explicación al cliente también pasó a Haiku en ese PR y se revirtió a
    Sonnet 5, porque omitía los motivos (ver la nota del ADR-0026).

## Hallazgo lateral

En las dos pruebas, y en la traza de Sonnet, los resultados llegaron sin
`page_age`. `fetch_threat_intel.py` descarta las filas sin fecha legible (guarda
de FP-10), así que muchas búsquedas no dejan ninguna fila. No cambia con este
fix. Se anota para revisar si el corpus debería guardar también las fuentes sin
fecha.

## Aprendizaje

Una llamada con herramientas del proveedor cobra también lo que el modelo hace
después de usarlas. Si el código sólo lee los bloques de la herramienta, todo lo
demás es gasto: hay que pedirle al modelo que no lo produzca y ponerle un tope.
