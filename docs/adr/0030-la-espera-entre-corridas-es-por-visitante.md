# ADR-0030: la espera entre corridas es por visitante, no global

- **Estado**: aceptado
- **Fecha**: 2026-10-02
- **Actualiza**: ADR-0025 (deja de mantenerse la espera por escenario en la API;
  el techo global no cambia).

## Contexto

Cada fila ejecutable del dashboard tenía dos esperas de 5 minutos:

- **En la API**, por escenario y en memoria del proceso. La compartían todos los
  visitantes.
- **En el navegador**, por fila, en el `localStorage` de cada visitante. Era sólo
  un espejo para mostrar la cuenta regresiva.

La de la API nació antes que el techo global (acta 10 §3.5), para cuidar el
costo. Desde ADR-0025 el costo lo acota el techo contado en la base (40
ejecuciones por hora, 200 por día), y la espera por escenario quedó sólo para
frenar el doble clic.

Con la demo publicada apareció su efecto: si A ejecuta una fila y B intenta la
misma dentro de los 5 minutos, B recibe un `429` ("Este escenario se corrió hace
poco…"). Pero en su tabla esa fila no muestra ninguna corrida, porque la tabla
es por visitante. B no sabe quién la corrió ni puede ver el resultado.

## Decisión

La espera entre corridas de una fila es **por visitante** y vive **sólo en el
navegador** (`COOLDOWN_MS` en `Transactions.tsx`, 5 minutos). La API deja de
tener espera por escenario. El único `429` de `POST /cases` es el techo de la
demo (ADR-0025).

## El riesgo que se midió antes

La espera global limitaba cuántas veces se repite un escenario: 12 por hora como
máximo. Cada corrida queda guardada con la fecha fija del escenario, así que el
historial del cliente crece con cada clic y no vence. El sufijo de dispositivo y
comercio (incidente 0008) protege FP-03 y FP-11. Faltaba saber si otra política
que mire el historial del cliente cambia el veredicto por repetición.

`tests/test_live_repetition.py` lo mide sobre las 14 filas ejecutables (vitrina,
escenarios de la tabla y diversos). Turna las filas de cada cliente y simula el
techo diario entero (200 corridas) sobre un solo cliente:

- Con el sufijo, ninguna fila cambia de veredicto ni de políticas.
- Sin el sufijo del comercio, los 12 clientes cambian (FP-11) entre la corrida 2
  y la 13. El test detecta la acumulación cuando existe.

## Alternativas descartadas

**Espera por ID de visitante enviado a la API.** El servidor la aplicaría por
persona, pero el ID se regenera borrando el `localStorage`. Protege lo mismo que
la del navegador, con más código.

**Espera por IP.** ADR-0025 ya la descartó para el costo. Además, una oficina o
una universidad comparten IP: gente de la misma empresa que llegue por el mismo
post compartiría la espera.

**Mantener la espera global y mostrar la corrida del otro visitante.** Convierte
el `429` en "mira el análisis en curso", pero sigue bloqueando a B por algo que
no hizo.

## Consecuencias

**Se gana**: cada visitante ejecuta cualquier fila sin depender de los demás; el
`429` sólo aparece cuando la demo alcanza su techo, con un mensaje que lo dice.

**Se paga**:

- Quien llame a la API directamente no tiene espera por fila. El costo sigue
  acotado por el techo global, igual que antes para cualquier `transaction_id`
  sin prefijo `LIVE-`.
- Un mismo escenario puede repetirse hasta el techo por hora (40) en vez de 12.
  El test de arriba es la guarda: si una política nueva mira el historial del
  cliente, falla antes del deploy.
