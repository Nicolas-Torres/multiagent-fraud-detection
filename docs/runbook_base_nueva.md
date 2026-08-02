# Runbook — poner en marcha una base de datos nueva

> Procedimiento repetible para dejar una base vacía lista para el sistema:
> local, compartida en AWS, o la que venga. Ocho pasos y sus verificaciones.
>
> **Regla que atraviesa todo el documento**: cada paso termina con una
> comprobación cuyo resultado se puede leer. Un paso que "no dio error" no es un
> paso verificado.

---

## 0. Antes de empezar: ¿es una base compartida?

Si otra persona la usa, **tres cosas cambian**:

- `seed.py --reset` hace `TRUNCATE ... CASCADE` y **arrastra los `cases`** de tu
  compañero. Nunca lo corras sin avisar.
- Las migraciones son globales: `alembic upgrade head` cambia el esquema para los
  dos.
- Los smoke tests escriben. Hoy limpian al salir, pero cualquiera nuevo que no lo
  haga contamina la tabla del otro.

Contra una base compartida: **se integra**, no se itera. Los experimentos van en
la local.

---

## 1. Crear la base, si el cluster es nuevo

```bash
uv run python scripts/create_database.py
```

Solo hace falta la primera vez contra un cluster. Si la base ya existe, el script
lo dice y sale sin hacer nada.

`DATABASE_URL` ya debe apuntar a la base **objetivo** (`fraud`), aunque todavía no
exista: el script lee ese nombre, se conecta a `postgres` en el mismo host con las
mismas credenciales, y la crea desde allá. No hay que editar el `.env` para esto
—hacerlo es la forma más fácil de dejarlo apuntando a `postgres` y terminar con
las tablas de la aplicación en la base de mantenimiento—.

Si el usuario no tiene permiso de `CREATEDB`, este paso lo hace quien administre
el cluster. En RDS el master sí puede.

## 2. Apuntar `DATABASE_URL`

En `.env`:

```
DATABASE_URL=postgresql+psycopg://usuario:password@host:5432/fraud?sslmode=require
```

Tres trampas, todas silenciosas:

**El password va percent-encoded.** Dentro de una URL no es un campo sino un tramo
delimitado por `:` y `@`; cualquier carácter estructural lo parte. Un `$` pegado al
`@` además se lo come Bash como expansión al hacer `source` —sin error ni
advertencia— y el resultado es un `authentication failed` que parece problema de
AWS. SQLAlchemy hace `unquote` al parsear, así que el driver recibe el literal.

```bash
python -c "from urllib.parse import quote; print(quote(input('password: '), safe=''))"
```

**`?sslmode=require` no es opcional en RDS.** Con `rds.force_ssl` activo, una
conexión sin TLS se rechaza en el handshake, antes de autenticar.

**La base es `fraud`, no `postgres`.** La que RDS provisiona por defecto queda como
base de mantenimiento. Apuntar ahí "funciona" y crea las tablas en el lugar
equivocado.

### Verificación

```bash
uv run python -c "
from multiagent_fraud_detection.config.settings import settings
u = settings.database_url
print(u.split('@')[-1])          # host, puerto y base, sin el password
print('TLS:', 'sslmode' in u)
"
```

> **Trampa de entorno**: una variable exportada en la shell gana sobre el `.env`
> y contamina también a `docker compose`. Si algo apunta a un sitio inesperado:
> `echo $DATABASE_URL` — debería estar vacío.

---

## 3. Confirmar que llegas, y a dónde

```bash
uv run python scripts/check_database.py
```
Devuelve código ≠ 0 si algo bloquea el arranque: versión de Postgres distinta de
la esperada, conexión a la base de mantenimiento, usuario sin permiso de crear
objetos, o pgvector no disponible en el cluster.

**Qué leer:**

| | Esperado |
|---|---|
| `version()` | PostgreSQL **18**.x |
| `current_database()` | `fraud` |
| `current_user` | el usuario de la app, no `postgres` |

La versión mayor importa: mientras local y nube difieran, *"pasa en local"* deja
de ser evidencia de *"pasa en la nube"*. La menor puede diferir (18.1 vs 18.3).

---

## 4. Habilitar pgvector

**Las extensiones son por base de datos, no por cluster.** Instalarla en
`postgres` no la habilita en `fraud`.

```sql
-- lo que el motor PUEDE instalar (no lo instalado)
SELECT name, default_version FROM pg_available_extensions WHERE name='vector';

-- lo que ESTÁ instalado en ESTA base
SELECT extname, extversion FROM pg_extension WHERE extname='vector';
```

Confundir las dos consultas es el error clásico: la primera devuelve una fila en
un cluster donde la extensión no está creada.

La primera migración (`c558fd490ae6`) hace `CREATE EXTENSION IF NOT EXISTS vector`,
así que normalmente el paso 4 la habilita sola. Si el usuario no tiene permiso
—en RDS el master es `rds_superuser`, no superusuario— hay que crearla con una
cuenta que sí lo tenga, antes de migrar.

---

## 5. Migrar

```bash
uv run alembic current          # vacío en una base nueva
uv run alembic upgrade head
uv run alembic current          # debe coincidir con el head del repo
uv run alembic check            # 0 = modelos y migraciones sincronizados
```

`alembic check` es el que atrapa el caso peor: migraciones aplicadas que no
reflejan los modelos actuales. Sin él, el error aparece al primer `INSERT`.

---

## 6. Verificar el esquema

```bash
docker compose exec db psql -U fraud -d fraud -c "\dt"
# o, contra AWS:
psql "$DATABASE_URL_PSQL" -c "\dt"
```

Ocho tablas más `alembic_version`:

```
transactions · customer_behaviors · cases · decisions
signals · human_resolutions · agent_errors · merchant_blacklist
```

Y los índices de historial, que son lo único que se puede aplicar mal sin fallar:

```sql
\d transactions
```

Deben estar `ix_transactions_customer_ts` y `ix_transactions_device_ts`, y **no**
debe estar `ix_transactions_customer_id` — el suelto se elimina por redundante.

---

## 7. Sembrar

```bash
uv run python scripts/validate_dataset.py   # los CSV, antes de tocar la base
uv run python scripts/seed.py
```

El validador primero: sembrar datos que no pasan su propia verificación llena la
base de algo que habrá que borrar.

Salida esperada: `1000 perfiles · 7000 transacciones (96 clientes sin perfil) ·
1 comercio en lista negra`.

Si la base ya tenía datos y el dataset se regeneró con **menos** filas, el upsert
no borra las huérfanas: ahí hace falta `--reset` (y avisar, si es compartida).

---

## 8. `ANALYZE` — el paso que se olvida

```sql
uv run python -c "
import asyncio, sys
if sys.platform=='win32': asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
from sqlalchemy import text
from multiagent_fraud_detection.db.session import engine
async def main():
    async with engine.begin() as c:
        for t in ['transactions','customer_behaviors','merchant_blacklist']:
            await c.execute(text(f'ANALYZE {t}'))
            print('analizada', t)
    await engine.dispose()
asyncio.run(main())
"
```

Tras una carga masiva, el planificador **no tiene estadísticas** hasta que
autovacuum pase, y eso puede tardar. Sin ellas estima mal la selectividad y puede
elegir `Seq Scan` donde el índice gana por 20×.

Es la causa más común de "el índice no sirve" justo después de sembrar. El
`EXPLAIN` que se corra antes de esto no dice nada.

---

## 9. Verificar de punta a punta

```bash
uv run python scripts/smoke_seed.py    # 18 comprobaciones
uv run python scripts/smoke_read.py    # round-trip de la capa Read
```

`smoke_seed.py` resiembra al empezar para comprobar idempotencia, así que correrlo
es también una segunda pasada del seed.

**Orden**: `smoke_seed` antes que `smoke_read`. El segundo escribe dos fixtures
propias; hoy las limpia al salir, pero el orden inverso fue lo que descubrió la
contaminación la primera vez.

### Comprobación final de coherencia

```sql
SELECT (SELECT count(*) FROM customer_behaviors)                  AS perfiles,
       (SELECT count(*) FROM transactions)                        AS transacciones,
       (SELECT count(DISTINCT customer_id) FROM transactions)     AS clientes,
       (SELECT count(*) FROM merchant_blacklist)                  AS blacklist,
       (SELECT count(*) FROM cases)                               AS casos;
```

`1000 · 7000 · 1095 · 1 · 0`

**`casos` debe ser 0.** El seed carga historial, no casos: crear un caso es correr
el pipeline. Si aparece un número distinto de cero en una base recién sembrada,
algo más escribió.

---

## Resumen ejecutable

```bash
# 1    configurar
uv run python scripts/create_database.py    # solo en cluster nuevo

# 2    confirmar destino
uv run python scripts/check_database.py     # destino, permisos, pgvector

# 3-4  extensión y esquema
uv run alembic upgrade head && uv run alembic check

# 5-6  datos
uv run python scripts/validate_dataset.py && uv run python scripts/seed.py

# 7    estadísticas
uv run python -c "
import asyncio, sys
if sys.platform=='win32': asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
from sqlalchemy import text
from multiagent_fraud_detection.db.session import engine
async def main():
    async with engine.begin() as c:
        for t in ['transactions','customer_behaviors','merchant_blacklist']:
            await c.execute(text(f'ANALYZE {t}'))
            print('analizada', t)
    await engine.dispose()
asyncio.run(main())
"

# 8    verificación
uv run python scripts/smoke_seed.py && uv run python scripts/smoke_read.py
```

---

## Si algo falla

| Síntoma | Causa probable |
|---|---|
| `authentication failed` con password correcto | Password sin percent-encoding, o `$` comido por la shell |
| Conexión rechazada sin llegar a autenticar | Falta `?sslmode=require` |
| Las tablas no aparecen donde esperabas | Apuntaste a `postgres` en vez de `fraud` |
| `type "vector" does not exist` | La extensión está en otra base, o el usuario no pudo crearla |
| `alembic check` distinto de cero | Un modelo cambió sin migración |
| El índice existe pero el plan usa `Seq Scan` | Falta `ANALYZE` (paso 7) |
| `docker compose` apunta a otro sitio | Variable exportada en la shell ganándole al `.env` |
| Conteos que no cuadran por 2 | Fixtures de un smoke test sin limpiar |
| Cero filas tras "sembrar exitosamente" | Falta el `commit`, o `--reset` corrió después |
