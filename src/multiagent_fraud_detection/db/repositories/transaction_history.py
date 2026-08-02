"""Consultas de historial de transacciones.

**Todas las consultas de historial pasan por acá.** Es el único punto donde se
hace cumplir el invariante *as-of*, y por eso existe el módulo: un invariante que
depende de que cada autor lo recuerde no es un invariante.

---

## El invariante *as-of*

Una transacción se juzga con lo que existía **en el instante en que ocurrió**,
nunca con lo que existe ahora. Toda consulta lleva `timestamp <= :as_of`, donde
`as_of` es el timestamp de la transacción bajo análisis — **jamás `now()`**.

Por qué importa, y por qué es fácil de pasar por alto:

En producción esto es imposible de violar: el futuro no está en la tabla cuando
llega el caso. En evaluación sí, porque el dataset se carga completo de una vez.
Un agente que no filtre **funciona bien en producción y solo falla en
evaluación** — y falla hacia arriba, viendo ráfagas completas desde su primera
transacción e inflando su propio recall. El harness certificaría un sistema que
no funciona.

El `<=` es inclusivo a propósito: la transacción bajo análisis cuenta para su
propia ventana. FP-03 dice "más de 3 en menos de 5 minutos" contando ésta.

---

## Dos funciones, dos ejes

| Eje | Políticas | Por qué |
|---|---|---|
| cliente | FP-04, FP-05, FP-11 | reconstruyen la actividad de la cuenta |
| dispositivo | FP-03 | un dispositivo usado con varias cuentas **es** la señal |

FP-03 no filtra por cliente: hacerlo escondería el caso que la política busca.
Por eso son dos consultas y dos índices, no uno.

Cada política acota su propia ventana en memoria sobre lo que estas funciones
devuelven. La alternativa —una consulta por política— multiplica los puntos
donde olvidar el `as_of` y los roundtrips que el grafo hace en paralelo.
"""

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from multiagent_fraud_detection.db.models import Transaction

# Ventana por defecto. La política más ancha es FP-11 ("mismo día"), y un día
# calendario local nunca supera las 24 h desde `as_of`... salvo en el cambio de
# horario de otoño, donde dura 25. Las dos horas de margen cubren ese caso sin
# tener que resolver la zona horaria acá.
DEFAULT_WINDOW = timedelta(hours=26)


def _window_stmt(as_of: datetime, window: timedelta):
    """Predicado temporal compartido. Acá vive el invariante."""
    return (
        Transaction.timestamp <= as_of,
        Transaction.timestamp > as_of - window,
    )


async def history_for_customer(
    session: AsyncSession,
    *,
    customer_id: str,
    as_of: datetime,
    window: timedelta = DEFAULT_WINDOW,
) -> list[Transaction]:
    """Actividad reciente de la cuenta, en orden cronológico.

    Sirve a FP-04, FP-05 y FP-11. Usa `ix_transactions_customer_ts`.
    """
    stmt = (
        select(Transaction)
        .where(Transaction.customer_id == customer_id, *_window_stmt(as_of, window))
        .order_by(Transaction.timestamp)
    )
    return list((await session.scalars(stmt)).all())


async def history_for_device(
    session: AsyncSession,
    *,
    device_id: str,
    as_of: datetime,
    window: timedelta = DEFAULT_WINDOW,
) -> list[Transaction]:
    """Actividad reciente del dispositivo, cruzando cuentas.

    Sirve a FP-03. Usa `ix_transactions_device_ts`.

    Deliberadamente **no** filtra por cliente: un dispositivo que opera con
    varias cuentas en minutos es exactamente lo que la política busca.
    """
    stmt = (
        select(Transaction)
        .where(Transaction.device_id == device_id, *_window_stmt(as_of, window))
        .order_by(Transaction.timestamp)
    )
    return list((await session.scalars(stmt)).all())
