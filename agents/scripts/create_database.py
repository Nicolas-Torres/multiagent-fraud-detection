"""Crea la base de datos de la aplicación en un cluster nuevo.

    uv run python scripts/create_database.py

Paso previo a todo lo demás: el único que corre cuando la base **todavía no
existe**. Después de éste, `check_database.py` y `alembic upgrade head`.

## Por qué no basta con conectar y ejecutar `CREATE DATABASE`

`DATABASE_URL` apunta a `fraud`, que es justamente lo que falta. Conectarse ahí
para crearla no puede funcionar.

La solución no es cambiar el `.env` a mano antes de correr el script y volver a
cambiarlo después: eso es un paso manual, no documentado y fácil de olvidar en el
sentido peligroso —dejarlo apuntando a `postgres` y crear las tablas de la
aplicación en la base de mantenimiento—.

En cambio, el script **deriva** la conexión: lee el nombre de la base objetivo de
`DATABASE_URL`, se conecta a `postgres` en el mismo host con las mismas
credenciales, y crea la base de allá. `DATABASE_URL` no se toca nunca.

`CREATE DATABASE` no corre dentro de una transacción, de ahí el
`isolation_level="AUTOCOMMIT"`.
"""

import sys

import sqlalchemy as sa

from src.config.settings import settings

# Base de mantenimiento: existe siempre y no es de nadie. Es el único sitio desde
# donde se puede crear otra.
BASE_MANTENIMIENTO = "postgres"


def _crear(sa, url: sa.engine.URL, objetivo: str) -> int:
    """Crea `objetivo` desde la base de mantenimiento. Idempotente."""
    engine = sa.create_engine(
        url.set(database=BASE_MANTENIMIENTO), isolation_level="AUTOCOMMIT"
    )

    with engine.connect() as conn:
        existe = conn.exec_driver_sql(
            "SELECT 1 FROM pg_database WHERE datname = %s", (objetivo,)
        ).fetchone()

        if existe:
            print(f"'{objetivo}' ya existe en {url.host} — nada que hacer")
            engine.dispose()
            return 0

        nombre = sa.sql.quoted_name(objetivo, quote=True)
        conn.exec_driver_sql(f'CREATE DATABASE "{nombre}"')
        print(f"creada '{objetivo}' en {url.host}")

    engine.dispose()
    return 0


def main() -> int:
    url = sa.engine.make_url(settings.database_url)
    objetivo = url.database

    if objetivo in {BASE_MANTENIMIENTO, "template1"}:
        print(
            f"DATABASE_URL apunta a '{objetivo}', la base de mantenimiento.\n"
            "Debe apuntar a la base de la aplicación (p. ej. 'fraud'): este "
            "script la crea a partir de ese nombre."
        )
        return 1

    rc = _crear(sa, url, objetivo)

    # MLflow corre en un servidor remoto propio (`MLFLOW_TRACKING_URI`), que
    # gestiona su propio backend: no hay base `mlflow` local que crear (D9).

    print("\nsigue:  uv run python scripts/check_database.py")
    return rc


if __name__ == "__main__":
    sys.exit(main())
