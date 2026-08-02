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

from multiagent_fraud_detection.config.settings import settings

# Base de mantenimiento: existe siempre y no es de nadie. Es el único sitio desde
# donde se puede crear otra.
BASE_MANTENIMIENTO = "postgres"


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

    engine = sa.create_engine(
        url.set(database=BASE_MANTENIMIENTO), isolation_level="AUTOCOMMIT"
    )

    with engine.connect() as conn:
        existe = conn.exec_driver_sql(
            "SELECT 1 FROM pg_database WHERE datname = %s", (objetivo,)
        ).fetchone()

        if existe:
            # Idempotente: correrlo de nuevo no es un error. `CREATE DATABASE`
            # no admite `IF NOT EXISTS`, así que la comprobación es explícita.
            print(f"'{objetivo}' ya existe en {url.host} — nada que hacer")
            engine.dispose()
            return 0

        # El nombre viene de nuestra propia configuración, no de entrada
        # externa, pero se cita igual: `CREATE DATABASE` no acepta parámetros
        # enlazados y la interpolación a ciegas es un hábito que no conviene
        # tener.
        nombre = sa.sql.quoted_name(objetivo, quote=True)
        conn.exec_driver_sql(f'CREATE DATABASE "{nombre}"')
        print(f"creada '{objetivo}' en {url.host}")

    engine.dispose()

    print("\nsigue:  uv run python scripts/check_database.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
