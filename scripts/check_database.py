"""Diagnóstico de una base de datos antes de migrar o sembrar.

    uv run python scripts/check_database.py

Responde tres preguntas, en este orden:

    1. ¿A dónde estoy conectado, exactamente?
    2. ¿Puedo hacer lo que necesito hacer?
    3. ¿Está pgvector *instalado en esta base*, o solo disponible en el cluster?

Es el paso 2-3 del runbook (`docs/runbook_base_nueva.md`) automatizado. Corre
**antes** de `alembic upgrade head`: descubrir que el usuario no puede crear
tablas a mitad de una migración es peor que descubrirlo antes.

Usa el engine **síncrono** a propósito: no necesita el shim de Windows para
psycopg3 async y funciona igual contra local y contra RDS. Un diagnóstico que
depende de la infraestructura que está diagnosticando sirve de poco.

Devuelve código ≠ 0 si algo bloquea el arranque.
"""

import sys

import sqlalchemy as sa

from multiagent_fraud_detection.config.settings import settings

# La versión mayor tiene que coincidir entre entornos: mientras difieran, "pasa
# en local" deja de ser evidencia de "pasa en la nube". La menor puede diferir.
POSTGRES_ESPERADO = 18


def main() -> int:
    url = sa.engine.make_url(settings.database_url)
    print(f"destino   {url.host}:{url.port}/{url.database}")
    print(f"TLS       {url.query.get('sslmode', 'NO CONFIGURADO')}")

    bloqueos: list[str] = []

    engine = sa.create_engine(settings.database_url)
    with engine.connect() as conn:
        def q(sql):
            return conn.exec_driver_sql(sql).fetchall()

        # --- dónde estoy ------------------------------------------------------
        base = q("SELECT current_database()")[0][0]
        usuario = q("SELECT current_user")[0][0]
        version = q("SHOW server_version")[0][0]
        mayor = int(version.split(".")[0])

        print(f"\nbase      {base}")
        print(f"usuario   {usuario}")
        print(f"postgres  {version}")

        if mayor != POSTGRES_ESPERADO:
            bloqueos.append(
                f"Postgres {mayor}, se esperaba {POSTGRES_ESPERADO}: "
                "local y nube deben coincidir en versión mayor"
            )

        # La base que RDS provisiona por defecto es de mantenimiento. Apuntar ahí
        # "funciona" y crea las tablas en el lugar equivocado.
        if base in {"postgres", "template1"}:
            bloqueos.append(
                f"conectado a la base de mantenimiento '{base}': "
                "la base de la aplicación es 'fraud'"
            )

        # --- qué puedo hacer --------------------------------------------------
        crea_tablas = q(
            "SELECT has_schema_privilege(current_user,'public','CREATE')"
        )[0][0]
        print(f"\ncrea tablas       {crea_tablas}")
        if not crea_tablas:
            bloqueos.append("el usuario no puede crear objetos en 'public'")

        # En RDS el master no es superusuario sino miembro de `rds_superuser`.
        # No es bloqueo por sí solo: importa para saber si podrá crear
        # extensiones que instalan código C.
        es_super = q("SELECT usesuper FROM pg_user WHERE usename = current_user")
        rol_rds = q(
            "SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='rds_superuser')"
        )[0][0]
        if rol_rds:
            miembro = q(
                "SELECT pg_has_role(current_user,'rds_superuser','member')"
            )[0][0]
            print(f"rds_superuser     {miembro}")
        else:
            print(f"superusuario      {bool(es_super and es_super[0][0])}")

        # --- pgvector ---------------------------------------------------------
        # Dos consultas distintas y confundirlas es el error clásico:
        # `pg_available_extensions` lista lo que el motor PUEDE instalar;
        # `pg_extension` lista lo instalado EN ESTA BASE. Las extensiones son
        # por base de datos, no por cluster.
        disponible = q(
            "SELECT default_version FROM pg_available_extensions WHERE name='vector'"
        )
        instalada = q("SELECT extversion FROM pg_extension WHERE extname='vector'")

        print(f"\npgvector disponible  {disponible[0][0] if disponible else 'NO'}")
        print(f"pgvector instalada   {instalada[0][0] if instalada else 'todavía no'}")

        if not disponible:
            bloqueos.append(
                "pgvector no está disponible en este cluster: "
                "sin él la primera migración falla"
            )

        # --- estado del esquema -----------------------------------------------
        revision = q(
            "SELECT version_num FROM alembic_version"
        ) if q(
            "SELECT to_regclass('public.alembic_version') IS NOT NULL"
        )[0][0] else []
        print(
            f"\nalembic   {revision[0][0] if revision else 'base sin migrar'}"
        )

        bases = [r[0] for r in q(
            "SELECT datname FROM pg_database WHERE NOT datistemplate ORDER BY 1"
        )]
        print(f"bases     {', '.join(bases)}")

    engine.dispose()

    if bloqueos:
        print(f"\n{len(bloqueos)} bloqueo(s):")
        for b in bloqueos:
            print(f"  - {b}")
        return 1

    print("\nOK — se puede migrar")
    return 0


if __name__ == "__main__":
    sys.exit(main())
