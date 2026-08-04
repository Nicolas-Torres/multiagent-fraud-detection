"""Carga el dataset sintético en Postgres.

    uv run python scripts/seed.py            # upsert (idempotente)
    uv run python scripts/seed.py --reset    # borra y recarga

Carga **historial**, no casos. Sembrar transacciones y perfiles no crea ningún
`case`: crear un caso es correr el pipeline, y eso lo hace el `POST /cases` o el
harness de evaluación. Así el muestreo para la demo se decide después sin tocar
este script.

---

## El adaptador

Es la frontera entre el dataset y el dominio: *un adaptador por fuente; el
dominio recibe datos canónicos*. Todo lo que el CSV trae en formato de archivo
—rangos como texto, listas separadas por `;`, el typo `chanel`— se traduce acá y
no vuelve a aparecer más adentro.

Ninguna traducción adivina. Las que podrían —una zona horaria mal escrita, un
enum desconocido— **fallan**, porque el schema Pydantic las rechaza antes de que
lleguen a la base.

## Idempotencia: upsert, no `DO NOTHING`

`ON CONFLICT DO UPDATE` por defecto. `DO NOTHING` parece la opción prudente y es
la peor: si el dataset se regenera y el seed vuelve a correr, no pasa nada, la
base conserva las filas viejas y uno cree que recargó. Fallo silencioso justo en
el dato que sostiene todas las métricas.

Es la versión por fila del principio que ya rige el nodo persistidor: **un
reintento sustituye, no acumula**. Que los casos existentes no se corrompan
cuando un perfil cambia ya está garantizado porque `cases.customer_snapshot` es
JSONB congelado, no un FK.

`--reset` existe para el caso en que el dataset nuevo tenga *menos* filas que el
viejo: el upsert no borra huérfanas. Arrastra `cases` por el FK, y por eso es
explícito y no el comportamiento por defecto.
"""

import argparse
import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from multiagent_fraud_detection.db.models import (
    CustomerBehavior,
    MerchantBlacklist,
    Transaction,
)
from multiagent_fraud_detection.db.session import engine

from _dataset import BLACKLIST, leer_perfiles, leer_transacciones

# 7 000 transacciones x 9 columnas son 63 000 parámetros, y psycopg corta en
# 65 535. Un solo INSERT pasaría raspando hoy y reventaría al agregar una
# columna. 500 deja margen sin volver lento el arranque.
BATCH = 500

Session = async_sessionmaker(engine, expire_on_commit=False)


async def _upsert(session, modelo, filas: list[dict], pk: str) -> None:
    """Inserta o actualiza por lotes. Un reintento sustituye, no acumula."""
    if not filas:
        return

    columnas = [k for k in filas[0] if k != pk]

    for i in range(0, len(filas), BATCH):
        lote = filas[i : i + BATCH]
        stmt = pg_insert(modelo).values(lote)
        stmt = stmt.on_conflict_do_update(
            index_elements=[pk],
            set_={c: stmt.excluded[c] for c in columnas},
        )
        await session.execute(stmt)


async def _reset(session) -> None:
    """Vacía las tres tablas.

    `CASCADE` arrastra `cases` y sus hijos por el FK sobre `transaction_id`. Por
    eso `--reset` es explícito: perder los casos analizados es una decisión, no
    un efecto colateral del arranque.
    """
    await session.execute(
        text(
            "TRUNCATE transactions, customer_behaviors, merchant_blacklist CASCADE"
        )
    )


async def sembrar(reset: bool) -> None:
    print("Leyendo y normalizando el dataset...")
    perfiles = leer_perfiles()
    transacciones = leer_transacciones()

    async with Session() as session:
        if reset:
            print("  --reset: vaciando tablas (arrastra cases por CASCADE)")
            await _reset(session)

        # Orden: perfiles antes que transacciones. No lo exige ningún FK —no hay
        # FK de `transactions.customer_id`, para que un cliente sin perfil pueda
        # operar— pero deja la base coherente en cualquier instante intermedio.
        await _upsert(
            session,
            CustomerBehavior,
            [p.model_dump() for p in perfiles],
            "customer_id",
        )
        await _upsert(
            session,
            Transaction,
            [t.model_dump() for t in transacciones],
            "transaction_id",
        )
        await _upsert(
            session,
            MerchantBlacklist,
            [b.model_dump() for b in BLACKLIST],
            "merchant_id",
        )

        # Un solo commit: o queda todo o no queda nada. Un seed a medias es peor
        # que no haber corrido, porque parece exitoso.
        await session.commit()

    sin_perfil = len(
        {t.customer_id for t in transacciones}
        - {p.customer_id for p in perfiles}
    )
    print(f"  {len(perfiles)} perfiles")
    print(f"  {len(transacciones)} transacciones "
          f"({sin_perfil} clientes sin perfil)")
    print(f"  {len(BLACKLIST)} comercios en lista negra")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--reset",
        action="store_true",
        help="vacía las tablas antes de cargar (arrastra cases por CASCADE)",
    )
    args = parser.parse_args()

    asyncio.run(sembrar(args.reset))
    return 0


if __name__ == "__main__":
    sys.exit(main())
