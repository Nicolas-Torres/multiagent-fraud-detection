"""Carga el dataset sintético y el catálogo de políticas en Postgres.

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

Para el catálogo el adaptador ya existe y es `FileCatalogSource`: este script no
vuelve a parsear los JSON, pide el `RawCatalog` y proyecta sus registros a las
tres tablas. Un solo lector para el archivo, acá y en el gate offline.

## Idempotencia: upsert, no `DO NOTHING`

`ON CONFLICT DO UPDATE` por defecto. `DO NOTHING` parece la opción prudente y es
la peor: si el dataset se regenera y el seed vuelve a correr, no pasa nada, la
base conserva las filas viejas y uno cree que recargó. Fallo silencioso justo en
el dato que sostiene todas las métricas.

Es la versión por fila del principio que ya rige el nodo persistidor: **un
reintento sustituye, no acumula**. Que los casos existentes no se corrompan
cuando un perfil cambia ya está garantizado porque `cases.customer_snapshot` es
JSONB congelado, no un FK.

La regla vale también para `fraud_policies`, aunque la tabla sea append-only por
versión. *Append-only* significa que publicar `2025.2` no pisa a `2025.1`; no
significa que una fila no pueda corregirse para volver a coincidir con el archivo
que la originó. Si el seed se negara a actualizar, la base y el repositorio
divergirían en silencio — y el gate `check_policies.py --source=db` estaría
midiendo contra una base vieja, que es exactamente el fallo que esta sección
existe para evitar.

`--reset` existe para el caso en que el dataset nuevo tenga *menos* filas que el
viejo: el upsert no borra huérfanas. Arrastra `cases` por el FK, y por eso es
explícito y no el comportamiento por defecto.
"""

import argparse
import asyncio
import sys
from collections.abc import Sequence

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from multiagent_fraud_detection.db.models import (
    BindingSet,
    CustomerBehavior,
    FraudPolicy,
    MerchantBlacklist,
    PolicyBinding,
    Transaction,
)
from multiagent_fraud_detection.config.settings import settings
from multiagent_fraud_detection.db.session import engine
from multiagent_fraud_detection.domain.catalog import FileCatalogSource

from _dataset import BLACKLIST, DATA_DIR, leer_perfiles, leer_transacciones

# 7 000 transacciones x 9 columnas son 63 000 parámetros, y psycopg corta en
# 65 535. Un solo INSERT pasaría raspando hoy y reventaría al agregar una
# columna. 500 deja margen sin volver lento el arranque.
BATCH = 500

POLICIES = DATA_DIR / "policies"

# El dataset sintético no trae quién publicó cada norma: es un supuesto del
# dataset, no del modelo. La columna existe porque el alta desde el dashboard
# (§3.3 del contrato) sí va a tener un humano detrás.
PUBLISHER = "banco"

Session = async_sessionmaker(engine, expire_on_commit=False)


async def _upsert(
    session, modelo, filas: list[dict], pk: str | Sequence[str]
) -> None:
    """Inserta o actualiza por lotes. Un reintento sustituye, no acumula.

    `pk` acepta una columna o varias: las tablas del catálogo tienen PK
    compuesta y el `ON CONFLICT` necesita todas.
    """
    if not filas:
        return

    claves = [pk] if isinstance(pk, str) else list(pk)
    columnas = [k for k in filas[0] if k not in claves]

    for i in range(0, len(filas), BATCH):
        lote = filas[i : i + BATCH]
        stmt = pg_insert(modelo).values(lote)
        stmt = stmt.on_conflict_do_update(
            index_elements=claves,
            set_={c: stmt.excluded[c] for c in columnas},
        )
        await session.execute(stmt)


async def _activar(session, version: str) -> None:
    """Deja `version` como el único set de vinculaciones activo.

    **Dos sentencias y no una.** `SET active = (version = :v)` en un solo
    `UPDATE` puede violar el índice parcial único a mitad de camino: si la fila
    nueva se actualiza antes que la vieja, hay un instante con dos activas, y un
    índice único no diferible lo rechaza ahí mismo. Apagar primero y encender
    después nunca pasa por ese estado.

    Que el seed active lo que carga es una decisión, no un descuido. El default
    de la columna es `false` —cargar un set no lo promueve— y eso protege a
    cualquier otro camino de escritura, empezando por el alta desde el
    dashboard. Pero este script *es* la instalación del catálogo del repositorio:
    si no lo activara, el despliegue quedaría con el motor sin catálogo, que es
    peor que el riesgo que el default evita.
    """
    await session.execute(
        text("UPDATE binding_sets SET active = false WHERE active AND version <> :v"),
        {"v": version},
    )
    await session.execute(
        text("UPDATE binding_sets SET active = true WHERE version = :v"),
        {"v": version},
    )


async def _reset(session) -> None:
    """Vacía las tablas de datos y las del catálogo.

    `CASCADE` arrastra `cases` y sus hijos por el FK sobre `transaction_id`, y
    `policy_chunks` por el FK compuesto a `fraud_policies`. Por eso `--reset` es
    explícito: perder los casos analizados es una decisión, no un efecto
    colateral del arranque.
    """
    await session.execute(
        text(
            "TRUNCATE transactions, customer_behaviors, merchant_blacklist, "
            "fraud_policies, binding_sets, policy_bindings, policy_chunks CASCADE"
        )
    )


def _catalogo() -> tuple[list[dict], dict, list[dict]]:
    """Proyecta el `RawCatalog` del archivo a filas de las tres tablas.

    El texto de la norma viaja en el JSON bajo el nombre que declara
    `fingerprint_field` —hoy `rule`—; la columna se llama `text`. El nombre de la
    columna es nuestro y estable, el del archivo es del formato de entrega. Acá
    se traduce una vez, y `DbCatalogSource` hace el camino inverso.
    """
    raw = FileCatalogSource(
        POLICIES / "fraud_policies_2025.1.json",
        POLICIES / "policy_bindings_2025.1.json",
    ).fetch()

    campo = raw.header.get("fingerprint_field", "rule")

    documentos = [
        {
            "policy_id": d["policy_id"],
            "version": d["version"],
            "text": d[campo],
            "created_by": PUBLISHER,
        }
        for d in raw.documents
    ]

    sobre = {
        "version": raw.header["binding_set_version"],
        "source_catalog": raw.header["source_catalog"],
        "fingerprint_algorithm": raw.header.get("fingerprint_algorithm", "sha256"),
        "fingerprint_field": campo,
        "reference_currency": raw.header.get("reference_currency", "USD"),
    }

    vinculaciones = [
        {
            "binding_set_version": sobre["version"],
            "policy_id": v["policy_id"],
            "source_version": v["source_version"],
            "source_fingerprint": v["source_fingerprint"],
            "action": v["action"],
            "condition": v.get("condition"),
            "excluded_reason": v.get("excluded_reason"),
            "active": v.get("active", True),
            "bound_by": v["bound_by"],
        }
        for v in raw.bindings
    ]

    return documentos, sobre, vinculaciones


async def sembrar(reset: bool) -> None:
    print("Leyendo y normalizando el dataset...")
    perfiles = leer_perfiles()
    transacciones = leer_transacciones()
    documentos, sobre, vinculaciones = _catalogo()

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

        # El catálogo, en orden de FK: documentos y sobre antes que las
        # vinculaciones, que apuntan a los dos. Acá el orden **sí** lo exige la
        # base: la FK compuesta a `fraud_policies(policy_id, version)` es lo que
        # convirtió en estructura la validación 5 del catálogo.
        await _upsert(session, FraudPolicy, documentos, ["policy_id", "version"])
        await _upsert(session, BindingSet, [sobre], "version")
        await _upsert(
            session,
            PolicyBinding,
            vinculaciones,
            ["binding_set_version", "policy_id"],
        )
        await _activar(session, sobre["version"])

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
    print(f"  {len(documentos)} políticas · {len(vinculaciones)} vinculaciones "
          f"· set {sobre['version']} activo")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--reset",
        action="store_true",
        help="vacía las tablas antes de cargar (arrastra cases por CASCADE); "
             "solo con ENVIRONMENT=local",
    )
    args = parser.parse_args()

    # El guard corre ANTES de tocar la base y antes de leer los CSV: si la
    # operación no está permitida, el proceso termina sin haber abierto una
    # conexión (ADR-0010).
    if args.reset and not settings.permite_operaciones_destructivas:
        print(
            f"--reset está bloqueado con ENVIRONMENT={settings.environment!r}.\n"
            f"Vacía las tablas de casos y resoluciones humanas por CASCADE, así "
            f"que solo se permite con ENVIRONMENT=local.\n"
            f"Sin --reset la carga es idempotente y no toca los casos existentes.",
            file=sys.stderr,
        )
        return 2

    asyncio.run(sembrar(args.reset))
    return 0


if __name__ == "__main__":
    sys.exit(main())
