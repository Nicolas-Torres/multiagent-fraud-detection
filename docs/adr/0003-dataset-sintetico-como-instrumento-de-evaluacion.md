# ADR-0003: el dataset sintético se diseña como instrumento de evaluación

- **Estado**: aceptado
- **Fecha**: 2026-08-02

## Contexto

El entregable 7 exige métricas —precisión, recall, F1— y comparación de enfoques.
Esas métricas se calculan sobre el dataset sintético, así que la calidad del
dataset acota la calidad de la evaluación.

El dataset original generaba transacciones plausibles y suficientes: 7 000 filas,
1 000 perfiles, once patrones de fraude. Al medirlo antes de usarlo aparecieron
dos huecos que lo hacían inservible para evaluar:

**Las tres dimensiones de decisión eran predictores perfectos.**

| Señal | Transacciones | De ellas, legítimas |
|---|---|---|
| país ≠ habitual | 186 | **0** |
| dispositivo ≠ habitual | 211 | **0** |
| canal ≠ habitual | 61 | **0** |

No existía un solo viaje legítimo, ni un cambio de teléfono, ni alguien que
probara la app un martes. La regla `país ≠ habitual → fraude` tenía **precisión
1.0**: un `if` de una línea ganaba.

**No había etiquetas.** El plan original era pedirlas al equipo de banca, que se
retiró del curso. El generador y el catálogo pasaron a ser nuestros.

## Decisión

El dataset se diseña como instrumento de medición, no como muestra de datos. Dos
consecuencias concretas:

**Se genera una población negativa difícil.** Ocho patrones de confusor —cuatro
de señal suelta legítima, cuatro de casi-positivo que fallan una condición por
poco— tallados del relleno, no sumados encima.

**El ground truth se computa evaluando las reglas del catálogo sobre el dataset**,
no registrando qué rama del generador disparó. Vive en `data/ground_truth.csv`,
archivo aparte: el sistema bajo evaluación nunca lo ve.

## Alternativas descartadas

**Etiquetar por la rama del generador.** Es lo obvio: el generador sabe qué
sorteó. Se descartó porque con confusores en el dataset un patrón "normal" puede
satisfacer una política por accidente —una compra cualquiera a 20 minutos de un
cambio de perfil—. Al implementarlo se comprobó: **14 transacciones satisfacen
dos políticas a la vez**. Etiquetadas por rama, esas 14 quedarían marcadas
`APPROVE` siendo positivos reales, y el harness castigaría al sistema por
acertar.

**Etiquetar solo los positivos.** Alcanza para recall y no para precisión: sin
saber qué transacciones *no* debían marcarse, no se puede contar un falso
positivo. Por eso hay una fila por cada una de las 7 000, incluidas las limpias.

**Poner las etiquetas como columnas de `transactions.csv`.** Obligaría al seed a
cargarlas —y entonces la respuesta queda al alcance de cualquier agente que
consulte historial— o a descartarlas en silencio, y entonces no se entiende por
qué están.

**Parchear el dataset existente agregando confusores encima.** Dejaría dos
poblaciones con reglas de generación distintas. Se regeneró completo.

## Consecuencias

**Se gana** una métrica que significa algo: el `if` de una línea pasó de precisión
100% a 16%. Y una defensa concreta para el entregable 7, que puede mostrar el
antes y el después en vez de afirmar que el dataset es adecuado.

**Se paga** un generador que ahora es código de proyecto y no un script
desechable: 700 líneas que hay que mantener, con el ground truth acoplado al texto
del catálogo. Cambiar el umbral de una política obliga a regenerar las etiquetas.

**La calidad de la medición está acotada por el diseño de los confusores.** Un
sistema podría aprender a distinguir exactamente los ocho patrones que
introdujimos y fallar con un noveno que no se nos ocurrió. Los confusores mejoran
la medición; no la vuelven representativa de producción.

**El dataset no es realista y no pretende serlo.** ~7 transacciones por cliente en
un mes, tipos de cambio fijos, cuentas mono-moneda. Es una maqueta de medición.
Las limitaciones están en `data/README.md` §9.
