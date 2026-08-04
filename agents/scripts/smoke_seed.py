"""Smoke test del seed: verifica lo que quedó en la base.

    uv run python scripts/seed.py
    uv run python scripts/smoke_seed.py

Seis comprobaciones. Cada una verifica algo que **falla en silencio**: ninguna
de estas rupturas lanza una excepción al sembrar, todas aparecerían como
métricas raras semanas después.

Relee en una **sesión nueva** para forzar el `SELECT` real contra Postgres y no
el identity map de la sesión que escribió — mismo patrón que `smoke_read.py`.

Cuando llegue `pytest` (entregable 5), cada `_check` se vuelve un test y este
archivo se tira. El trabajo no se pierde: se reordena.
"""

import asyncio
import sys
from collections import Counter
from datetime import timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.db.models import (
    CustomerBehavior,
    MerchantBlacklist,
    Transaction,
)
from src.db.repositories.transaction_history import (
    history_for_customer,
)
from src.db.session import engine
from src.schemas.customer_behavior import CustomerBehaviorRead
from src.schemas.transaction import TransactionRead

from seed import sembrar  # scripts/ está en sys.path al ejecutar este archivo

Session = async_sessionmaker(engine, expire_on_commit=False)

PERFILES = 1000
TRANSACCIONES = 7000

fallas: list[str] = []


def _check(condicion: bool, etiqueta: str, detalle: str = "") -> None:
    if condicion:
        print(f"  ok   {etiqueta}")
    else:
        print(f"  FALLA {etiqueta} {detalle}")
        fallas.append(etiqueta)


async def check_conteos(session) -> None:
    perfiles = await session.scalar(select(func.count()).select_from(CustomerBehavior))
    transacciones = await session.scalar(select(func.count()).select_from(Transaction))
    blacklist = await session.scalar(select(func.count()).select_from(MerchantBlacklist))

    _check(perfiles == PERFILES, "1000 perfiles", f"({perfiles})")
    _check(transacciones == TRANSACCIONES, "7000 transacciones", f"({transacciones})")
    _check(blacklist == 1, "M-999 en lista negra", f"({blacklist})")

    # La asimetría es deliberada: hay perfiles sin transacciones y transacciones
    # de clientes sin perfil. Lo segundo es el escenario que v0.3 llamó "el que
    # más importa" —un cliente sin historial no es un error, es el más
    # sospechoso— y el contrato lo declara válido con `CaseDetail.customer` nulo.
    huerfanas = await session.scalar(
        select(func.count(func.distinct(Transaction.customer_id))).where(
            ~Transaction.customer_id.in_(select(CustomerBehavior.customer_id))
        )
    )
    _check(huerfanas > 50, "clientes sin perfil presentes", f"({huerfanas})")


async def check_normalizacion(session) -> None:
    """Las traducciones del adaptador sobrevivieron el viaje a Postgres."""
    perfiles = list(
        (await session.scalars(select(CustomerBehavior).limit(200))).all()
    )

    # `"10-20"` → dos enteros. Si el split fallara, la ventana horaria quedaría
    # en 0 y FP-01 marcaría todo como fuera de horario.
    _check(
        all(0 <= p.usual_hour_start <= 23 and 0 <= p.usual_hour_end <= 23 for p in perfiles),
        "usual_hours partido en dos enteros",
    )

    # `"PE;ES"` → lista real, `""` → lista vacía. Una celda vacía convertida en
    # `[""]` haría que "sin dispositivo habitual" pareciera "un dispositivo
    # llamado cadena vacía", y el contraste device_id != usual_devices dejaría
    # de disparar.
    _check(
        all("" not in p.usual_countries and "" not in p.usual_devices for p in perfiles),
        "listas sin elementos vacíos",
    )

    # Los montos son Decimal exactos, no float. Un float acá perdería centavos
    # y `Numeric(12,2)` los redondearía sin avisar.
    _check(
        all(isinstance(p.usual_amount_avg, Decimal) for p in perfiles)
        and all(-p.usual_amount_avg.as_tuple().exponent <= 2 for p in perfiles),
        "montos como Decimal de 2 decimales",
    )

    # Toda zona horaria es IANA resoluble. Es la validación cuyo error no se
    # nota hasta que corre un agente: una zona mal escrita no rompe la escritura,
    # corre la ventana horaria varias horas y FP-01 evalúa otra franja.
    zonas = {p.timezone for p in perfiles}
    invalidas = []
    for z in zonas:
        try:
            ZoneInfo(z)
        except Exception:
            invalidas.append(z)
    _check(not invalidas, f"{len(zonas)} zonas IANA válidas", str(invalidas))

    # `chanel` → `channel`, y el valor llegó como miembro del enum, no como
    # texto suelto.
    tx = list((await session.scalars(select(Transaction).limit(200))).all())
    _check(
        all(t.channel.value in {"web", "mobile"} for t in tx),
        "chanel renombrado y parseado como enum",
    )


async def check_casos_limite(session) -> None:
    """Los escenarios que el contrato declara válidos existen en la base."""
    nocturnos = await session.scalar(
        select(func.count()).select_from(CustomerBehavior).where(
            CustomerBehavior.usual_hour_start > CustomerBehavior.usual_hour_end
        )
    )
    _check(nocturnos > 30, "clientes nocturnos (start > end)", f"({nocturnos})")

    sin_dispositivo = await session.scalar(
        select(func.count()).select_from(CustomerBehavior).where(
            func.cardinality(CustomerBehavior.usual_devices) == 0
        )
    )
    _check(sin_dispositivo > 10, "perfiles sin dispositivo habitual", f"({sin_dispositivo})")

    multipais = await session.scalar(
        select(func.count()).select_from(CustomerBehavior).where(
            func.cardinality(CustomerBehavior.usual_countries) > 1
        )
    )
    _check(multipais > 10, "perfiles multi-país", f"({multipais})")

    segmentos = Counter(
        (await session.scalars(select(CustomerBehavior.segment))).all()
    )
    _check(len(segmentos) == 3, "los tres segmentos presentes", str(dict(segmentos)))


async def check_moneda_de_cuenta(session) -> None:
    """La moneda de la transacción es la de la cuenta, no la del país.

    Es la enmienda §1.2 convertida en assert. Si esto se rompiera, comparar
    `amount` con `usual_amount_avg` mezclaría unidades y todos los umbrales
    relativos —FP-01, FP-06, FP-08— evaluarían basura.
    """
    discrepantes = await session.scalar(
        select(func.count())
        .select_from(Transaction)
        .join(
            CustomerBehavior,
            Transaction.customer_id == CustomerBehavior.customer_id,
        )
        .where(Transaction.currency != CustomerBehavior.currency)
    )
    _check(discrepantes == 0, "moneda de tx == moneda de la cuenta", f"({discrepantes})")


async def check_as_of(session) -> None:
    """El repositorio de historial no devuelve el futuro.

    La comprobación más importante del archivo, porque es la que **no se puede
    hacer en producción**: allá el futuro no está en la tabla cuando llega el
    caso, así que un agente que no filtre parece funcionar. Solo se rompe en
    evaluación, y hacia arriba: vería ráfagas completas desde su primera
    transacción e inflaría su propio recall.
    """
    pivote = await session.scalar(
        select(Transaction).order_by(Transaction.timestamp).offset(3500).limit(1)
    )
    historial = await history_for_customer(
        session,
        customer_id=pivote.customer_id,
        as_of=pivote.timestamp,
        window=timedelta(days=365),
    )

    _check(
        all(t.timestamp <= pivote.timestamp for t in historial),
        "el historial no incluye el futuro",
    )
    _check(
        any(t.transaction_id == pivote.transaction_id for t in historial),
        "el historial incluye la transacción bajo análisis (<= inclusive)",
    )
    _check(
        historial == sorted(historial, key=lambda t: t.timestamp),
        "el historial viene en orden cronológico",
    )


async def check_frontera_read(session) -> None:
    """Lo persistido valida contra los schemas de la frontera pública."""
    perfil = await session.scalar(select(CustomerBehavior).limit(1))
    tx = await session.scalar(select(Transaction).limit(1))
    try:
        CustomerBehaviorRead.model_validate(perfil)
        TransactionRead.model_validate(tx)
        _check(True, "las filas validan contra los schemas Read")
    except Exception as exc:  # noqa: BLE001
        _check(False, "las filas validan contra los schemas Read", str(exc))


async def main() -> int:
    # Idempotencia: sembrar de nuevo sobre una base ya sembrada no debe mover
    # ningún conteo. `ON CONFLICT DO UPDATE` sustituye; no acumula.
    print("Resembrando para verificar idempotencia...")
    async with Session() as s:
        antes = await s.scalar(select(func.count()).select_from(Transaction))
    await sembrar(reset=False)
    async with Session() as s:
        despues = await s.scalar(select(func.count()).select_from(Transaction))
    _check(antes == despues, "resembrar no duplica filas", f"({antes} -> {despues})")

    # Sesión nueva: fuerza el SELECT real contra Postgres.
    async with Session() as session:
        print("\nConteos")
        await check_conteos(session)
        print("\nNormalización del adaptador")
        await check_normalizacion(session)
        print("\nCasos límite")
        await check_casos_limite(session)
        print("\nCoherencia de moneda")
        await check_moneda_de_cuenta(session)
        print("\nInvariante as-of")
        await check_as_of(session)
        print("\nFrontera Read")
        await check_frontera_read(session)

    await engine.dispose()

    if fallas:
        print(f"\n{len(fallas)} falla(s): {', '.join(fallas)}")
        return 1
    print("\nOK")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
