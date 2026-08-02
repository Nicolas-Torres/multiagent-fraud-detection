# ADR-0004: las consultas de historial son *as-of*, nunca *now()*

- **Estado**: aceptado
- **Fecha**: 2026-08-02

## Contexto

`transactions` cumple dos papeles a la vez: es la **fuente de casos** —de ahí sale
la transacción que se analiza— y es el **historial** que consultan cuatro
políticas de secuencia (FP-03 velocity, FP-04 card testing, FP-05 geolocalización,
FP-11 fraccionamiento).

El conflicto aparece porque el seed carga las 7 000 transacciones de una vez,
incluidas las de fechas posteriores. Si un agente analiza una transacción del 10
de diciembre y consulta "actividad reciente del cliente" sin acotar por fecha, la
base le devuelve también transacciones del 11, del 12 y del 20. **En el instante
en que la transacción ocurrió, esas no existían.**

Lo insidioso es la asimetría entre entornos: en producción esto es **imposible de
violar** —el futuro no está en la tabla cuando llega el caso—, así que un agente
sin filtro funciona perfectamente allá y solo falla en evaluación. Y falla hacia
arriba: ve ráfagas completas desde su primera transacción, detecta patrones que el
sistema real no podría, e infla su propio recall. El harness certificaría un
sistema que no funciona.

## Decisión

Toda consulta de historial lleva `timestamp <= :as_of`, donde `as_of` es el
timestamp de la transacción bajo análisis — **nunca `now()`**. El `<=` es
inclusivo: la transacción cuenta para su propia ventana, que es lo que FP-03
necesita ("más de 3 en menos de 5 minutos, contando ésta").

Se hace cumplir en un único módulo, `db/repositories/transaction_history.py`, con
dos funciones —una por eje de acceso, cliente y dispositivo—. Ninguna otra parte
del sistema consulta `transactions` para historial.

El ground truth respeta el mismo invariante: en una ráfaga de cuatro, solo la que
**cierra** el patrón lleva la etiqueta. Cuando llegó la primera, el patrón no
existía y aprobarla era correcto.

## Alternativas descartadas

**Cargar solo el historial anterior a un corte.** Resolvería el problema de raíz
—el futuro simplemente no estaría en la tabla— pero obligaría a recargar la base
por cada caso analizado. Inviable para un harness de cientos de casos.

**Confiar en que cada agente filtre.** Es lo que ocurre por omisión si no se
decide nada. Se descartó porque el olvido es invisible: no hay excepción, no hay
log, y el síntoma —métricas mejores de lo esperado— se confunde con éxito. *Un
invariante que depende de que cada autor lo recuerde no es un invariante.*

**Una consulta por política, cada una con su ventana.** Permitiría índices
ajustados a cada patrón, pero multiplica por cuatro los lugares donde olvidar el
`as_of` y los roundtrips que el grafo hace en paralelo.

**Una sola consulta para todas las políticas.** Fue la propuesta inicial y estaba
mal: FP-03 filtra por **dispositivo, no por cliente**, porque un dispositivo usado
con varias cuentas es exactamente la señal que busca. Una consulta por
`customer_id` nunca vería ese caso. De ahí que sean dos funciones y dos índices.

## Consecuencias

**Se gana** un cuello de botella único donde el invariante es verificable. El
smoke test del seed lo comprueba directamente —es la única comprobación del
archivo que *no se puede hacer en producción*—.

**Se paga** una indirección: ningún nodo consulta `transactions` por su cuenta,
aunque necesite algo que las dos funciones no devuelven. Cuando aparezca ese
caso, la salida correcta es agregar una tercera función al módulo, no una consulta
suelta en el nodo.

**Las funciones traen filas que alguna política no usa.** FP-11 filtra por
comercio en memoria sobre lo que ya trajo el índice de cliente. Es el costo
deliberado de no tener un tercer índice `(customer_id, merchant_id, timestamp)`.

**La ventana por defecto es de 26 horas, no 24.** La política más ancha es FP-11
("mismo día") y un día calendario local puede durar 25 horas en el cambio de
horario de otoño. El margen evita resolver la zona horaria dentro de la consulta.

**Índices medidos, no supuestos.** Sobre el dataset sembrado, el `Index Scan` usa
4 páginas contra 81 del `Seq Scan` forzado, y evita un nodo `Sort` porque el
compuesto entrega las filas ya ordenadas. `Rows Removed by Filter: 6 995` es el
argumento en una línea, y esa proporción crece con la tabla.
