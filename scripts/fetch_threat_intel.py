"""Recoge y congela la inteligencia externa gobernada. ADR-0014.

    uv run python scripts/fetch_threat_intel.py            # busca y siembra
    uv run python scripts/fetch_threat_intel.py --dry-run  # muestra las queries, no busca
    uv run python scripts/fetch_threat_intel.py --fake     # sin red ni clave, snapshot propio

Único punto del sistema que toca la red en el camino del dato: en runtime, el
nodo `external_threat_intel` sólo hace *lookup* sobre lo que este script ya
congeló bajo `SNAPSHOT_VERSION`.

## El allowlist gobierna antes de gastar nada

Un allowlist vacío falla ruidosamente, no calladamente: sin esta guarda el
script pagaría una búsqueda por emisor y no guardaría ninguna fila, que se lee
igual que "no hay alertas" — el peor de los dos fallos, porque no avisa.

## La URL sale del bloque de resultado; el allowlist decide sobre lo que volvió

`allowed_domains` en la herramienta del proveedor es optimización de costo, no
gobernanza: la garantía la da `intel/governance.enforce()` sobre lo que
efectivamente volvió, no sobre lo que se pidió (ADR-0014).

## Idempotencia

`ON CONFLICT` sobre `uq_threat_indicators_observation`
(`indicator_type, value, observed_at, snapshot_version`) actualiza en vez de
duplicar. **Verificación que importa**: correrlo dos veces sobre el mismo
corpus deja el mismo número de filas.
"""

import argparse
import asyncio
import sys
from datetime import datetime, time, timezone

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from multiagent_fraud_detection.config.settings import settings
from multiagent_fraud_detection.db.models import ThreatIndicator, Transaction
from multiagent_fraud_detection.db.repositories.web_search_allowlist import (
    active_domains,
)
from multiagent_fraud_detection.db.session import engine
from multiagent_fraud_detection.enums import IndicatorType
from multiagent_fraud_detection.intel.governance import enforce
from multiagent_fraud_detection.intel.searcher import (
    AnthropicSearcher,
    FakeSearcher,
    SearchResult,
    Searcher,
    parse_page_age,
)
from multiagent_fraud_detection.intel.snapshot import (
    FAKE_SNAPSHOT_VERSION,
    SNAPSHOT_VERSION,
    build_query,
)

# Quién queda registrado como autor de la fila. No es una persona: es el
# proceso que la trajo, igual que `PUBLISHER = "banco"` en `seed.py`.
ADDED_BY = "fetch_threat_intel"

# Resultado fijo para `--fake`: exercita el pipeline completo —upsert incluido—
# sin red ni clave, bajo `FAKE_SNAPSHOT_VERSION`. Mismo criterio que
# `FakeEmbedder` en `index_policies.py --fake`: no es ruido, es contenido
# determinista para poder verificar la idempotencia sin gastar cuota.
_RESULTADO_FALSO = SearchResult(
    url="https://sbs.gob.pe/alertas/fake",
    title="Alerta simulada (--fake)",
    page_age="April 30, 2025",
)

Session = async_sessionmaker(engine, expire_on_commit=False)

# Columnas que se refrescan en un re-fetch. La clave de conflicto
# (`indicator_type, value, observed_at, snapshot_version`) no se puede tocar
# por definición, y `added_by` se conserva del alta original — igual que
# `added_at`, que ni siquiera viaja en la fila y queda en su `server_default`.
_COLUMNAS_ACTUALIZABLES = ("retrieved_at", "source_url", "summary", "active")


async def _emisores(session) -> tuple[str, ...]:
    """`issuer_bank` distintos del dataset, sin nulos y en orden estable."""
    stmt = (
        select(Transaction.issuer_bank)
        .where(Transaction.issuer_bank.is_not(None))
        .distinct()
    )
    filas = (await session.scalars(stmt)).all()
    return tuple(sorted(filas))


def _fila(
    emisor: str, resultado: SearchResult, snapshot_version: str, ahora: datetime
) -> dict | None:
    """Una fila de `threat_indicators`, o `None` si la fecha no se puede leer.

    `parse_page_age` da una fecha, no una hora: se ancla a medianoche UTC
    porque el proveedor no informa más precisión que eso.
    """
    fecha = parse_page_age(resultado.page_age)
    if fecha is None:
        return None

    return {
        "indicator_type": IndicatorType.ISSUER,
        "value": emisor,
        "observed_at": datetime.combine(fecha, time.min, tzinfo=timezone.utc),
        "retrieved_at": ahora,
        "source_url": resultado.url,
        "summary": resultado.title,
        "snapshot_version": snapshot_version,
        "active": True,
        "added_by": ADDED_BY,
    }


def _recoger(
    searcher: Searcher,
    emisores: tuple[str, ...],
    allowlist: frozenset[str],
    snapshot_version: str,
) -> tuple[list[dict], list[tuple[str, str]], list[str]]:
    """Busca cada emisor y aplica las dos guardas: allowlist y fecha legible.

    Devuelve las filas listas para upsert, lo rechazado por el allowlist
    —`(url, motivo)`— y las URLs que pasaron el allowlist pero traían una
    fecha de publicación no reconocible.
    """
    ahora = datetime.now(timezone.utc)
    filas: list[dict] = []
    rechazadas: list[tuple[str, str]] = []
    sin_fecha: list[str] = []

    for emisor in emisores:
        resultados = searcher.search(build_query(emisor), allowlist)

        urls = [r.url for r in resultados]
        aceptadas, rechazos = enforce(urls, allowlist)
        rechazadas.extend((r.url, r.reason) for r in rechazos)

        aceptadas_set = set(aceptadas)
        for resultado in resultados:
            if resultado.url not in aceptadas_set:
                continue
            fila = _fila(emisor, resultado, snapshot_version, ahora)
            if fila is None:
                sin_fecha.append(resultado.url)
            else:
                filas.append(fila)

    return filas, rechazadas, sin_fecha


async def _upsert(session, filas: list[dict]) -> None:
    if not filas:
        return

    # Postgres rechaza `ON CONFLICT DO UPDATE` si dos filas del mismo INSERT
    # apuntan a la misma clave de conflicto — puede pasar si el proveedor
    # devuelve la misma URL dos veces para el mismo emisor. Se dedupea antes
    # de que llegue a la base, no después de que falle.
    unicas = list(
        {
            (f["indicator_type"], f["value"], f["observed_at"]): f for f in filas
        }.values()
    )

    stmt = pg_insert(ThreatIndicator).values(unicas)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_threat_indicators_observation",
        set_={c: stmt.excluded[c] for c in _COLUMNAS_ACTUALIZABLES},
    )
    await session.execute(stmt)


async def _correr(dry_run: bool, fake: bool) -> int:
    snapshot_version = FAKE_SNAPSHOT_VERSION if fake else SNAPSHOT_VERSION
    searcher: Searcher = FakeSearcher(results=(_RESULTADO_FALSO,)) if fake else AnthropicSearcher()

    print(f"snapshot {snapshot_version}")
    if fake:
        print("  --fake: sin red ni clave; los resultados no son reales")

    async with Session() as session:
        emisores = await _emisores(session)
        allowlist = await active_domains(session)

        if not allowlist:
            print(
                "el allowlist está vacío: sin fuentes autorizadas, cada búsqueda "
                'se pagaría y no guardaría ninguna fila — lo mismo que se lee como '
                '"sin alertas". Sembrá `web_search_allowlist` antes de correr esto '
                "(`uv run python scripts/seed.py`).",
                file=sys.stderr,
            )
            return 2

        print(f"  {len(emisores)} emisores · allowlist: {', '.join(sorted(allowlist))}")

        if dry_run:
            print("\n--dry-run: queries que se ejecutarían, sin gastar búsquedas")
            for emisor in emisores:
                print(f"  {emisor}: {build_query(emisor)}")
            return 0

        filas, rechazadas, sin_fecha = _recoger(
            searcher, emisores, allowlist, snapshot_version
        )

        # Un solo commit: o queda todo o no queda nada. Mismo criterio que
        # `seed.py` y `index_policies.py`.
        await _upsert(session, filas)
        await session.commit()

        total = await session.scalar(
            select(func.count())
            .select_from(ThreatIndicator)
            .where(ThreatIndicator.snapshot_version == snapshot_version)
        )

    print(f"\n{len(filas)} filas propuestas · {total} filas en el snapshot {snapshot_version}")

    if rechazadas:
        print(f"\nrechazadas por el allowlist ({len(rechazadas)}):")
        for url, motivo in rechazadas:
            print(f"  {url} — {motivo}")

    if sin_fecha:
        print(f"\ndescartadas por fecha de publicación no reconocible ({len(sin_fecha)}):")
        for url in sin_fecha:
            print(f"  {url}")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="muestra las queries que se ejecutarían, sin buscar ni escribir",
    )
    parser.add_argument(
        "--fake",
        action="store_true",
        help="sin red ni clave, contenido determinista bajo un snapshot propio",
    )
    args = parser.parse_args()

    if not args.dry_run and not args.fake and not settings.anthropic_api_key:
        print(
            "falta ANTHROPIC_API_KEY. Usá --fake para correr sin clave, o "
            "--dry-run para ver las queries sin buscar.",
            file=sys.stderr,
        )
        return 2

    return asyncio.run(_correr(dry_run=args.dry_run, fake=args.fake))


if __name__ == "__main__":
    sys.exit(main())
