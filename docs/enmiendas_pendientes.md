# Enmiendas pendientes — Contrato de Interfaz

**Estado**: acumulando hacia v0.5. Se consolidan en `contrato_de_interfaz.md` al
cerrar la etapa de **dataset y seed**.

> Documento de trabajo: se **vacía** al publicar una versión, no se archiva.
> Nunca hay dos. Vigente: v0.4.
>
> Contexto: [`briefing_dataset.md`](briefing_dataset.md) (§1.1–1.4, §2.1–2.5) y la puesta en marcha de la base compartida en AWS (§1.5–1.7, §2.6–2.8).

---

## 1. Decididas — listas para redactar

| # | Enmienda | Toca |
|---|---|---|
| 1 | Muere el supuesto `America/Lima` | §2.7 |
| 2 | `CustomerBehavior` gana `currency` y `timezone` | §2.5 |
| 3 | `CustomerBehavior` gana siete campos de evaluación de políticas | §2.5 |
| 4 | ~~`Transaction` gana `issuer_bank`~~ — **retirada** (§1.3) | — |
| 5 | Índices de historial en `transactions` | §7 |
| 6 | La forma de `DATABASE_URL` cambia: TLS y password codificado | §1.4 |
| 7 | Postgres destino sube a **18** | §1.4 |
| 8 | Tres entornos de base de datos, no uno | §1.4 |
| 9 | Precedencia entre políticas que aplican a la vez | §2.2 |
| 10 | Idempotencia del seed: upsert | — (implementación) |

### 1.1 — Muere el supuesto de zona horaria única

§2.7 de v0.4 ya lo marca como 🔶. El dataset tiene **siete países**; interpretar
la ventana horaria de un cliente en Madrid como hora de Lima la corre siete horas
y evalúa otra cosa. Afecta al 86% de los clientes.

**Resolución**: `timezone` (IANA) como columna del perfil. El seed la deriva del
país mientras la fuente no la traiga —una aproximación del adaptador, no del
dominio—. Derivarla en tiempo de lectura no sirve: US abarca seis zonas y MX tres.

Descartado guardar la ventana ya convertida a UTC: el horario de verano hace que
la conversión no sea constante, y hornearía un supuesto de estación.

### 1.2 — La moneda es atributo de la cuenta

`usual_amount_avg` es hoy un número sin moneda. Con el dataset, 77 de 999 clientes
tienen historial en dos monedas, y comparar "3x el promedio" entre ellas fabrica
falsos positivos.

**Resolución**: `currency` en el perfil, constante por cliente. No es una
simplificación: una tarjeta liquida en la moneda de la cuenta, no en la del país
donde ocurre la compra. La dimensión internacional sobrevive intacta porque
`country` sigue variando.

Fuera de alcance, documentado: cuentas multi-moneda y conversión FX.

### 1.3 — Campos nuevos del perfil

> **Corrección de numeración.** El análisis previo leyó los comentarios del
> generador en vez del catálogo, y a partir de la octava política se corrían un
> número. El catálogo real es `FP-01`…`FP-11` **sin huecos**: no falta `FP-08`
> ni existe `FP-12`. Los identificadores de abajo son los correctos.

| Campo | Habilita |
|---|---|
| `usual_channel` | FP-06 canal nuevo con monto alto |
| `account_creation_date` | FP-08 cuenta nueva + monto > 5× del segmento |
| `last_profile_update` | FP-09 cambio de datos + transacción inmediata |
| `daily_limit` | FP-11 fraccionamiento |
| `currency` | corrección §1.2 |
| `timezone` | corrección §1.1 |
| `segment` | FP-08 — el promedio contra el que compara |

**`issuer_bank` no se modela.** Era el insumo de FP-10 (alerta pública sobre el
emisor/BIN) y de nada más. Con FP-10 fuera del alcance —§2.4—, sería una columna
sin consumidor. Se queda en el CSV como dato de origen; modelarla es una
migración de una línea el día que exista un proveedor de alertas real.

Consecuencia: **`Transaction` no cambia**. Esa tabla solo recibe índices (§1.4).

### 1.4 — Índices de historial

Cuatro políticas (FP-03, 04, 05, 11) evalúan **secuencias**, no transacciones
sueltas. Necesitan `transactions (customer_id, timestamp)` y
`(device_id, timestamp)`.

Al crear el compuesto, el índice suelto en `customer_id` queda redundante —es un
prefijo por la izquierda— y se elimina en la misma migración.

### 1.5 — La forma de `DATABASE_URL` cambia

RDS trae `rds.force_ssl` activo: una conexión sin TLS se rechaza en el handshake,
antes de autenticar. La URL necesita `?sslmode=require`.

Y el password viaja **percent-encoded**. No es cosmético: dentro de una URL el
password no es un campo, es un tramo delimitado por `:` y `@`, así que cualquier
carácter estructural lo parte. Un `$` final pegado al `@` (`...pass$@host`) se lo
come Bash como expansión de parámetros posicionales al hacer `source` —sin error
ni advertencia—: password mutilado y `authentication failed` que parece problema
de AWS.

**Resolución**: `?sslmode=require` es parte de la forma esperada de
`DATABASE_URL`, y §1.4 documenta que el valor inyectado desde los Secrets del CD
viene codificado. SQLAlchemy hace `unquote` al parsear, así que el driver recibe
el password literal: es el mecanismo previsto, no un parche.

El `%` no rompe Alembic porque `env.py` inyecta la URL desde `settings` con
`create_engine` directo, sin pasar por el `ConfigParser` de `alembic.ini`. Aquella
decisión paga aquí.

### 1.6 — Postgres destino sube a 18

La instancia compartida corre **PostgreSQL 18.3**; el compose local corría 17.
Mientras difieran, "pasa en local" deja de ser evidencia de "pasa en la nube".

**Resolución**: 18 es la versión destino. `compose.yml` ya está alineado, y el job
de CI fija `pgvector/pgvector:pg18` como `services:` cuando se escriba (§1.6 del
contrato). La versión menor puede diferir —18.1 local vs 18.3 en RDS—: mismo
formato en disco, mismo SQL.

pgvector disponible en la instancia: 0.8.1.

### 1.7 — Tres entornos de base de datos, no uno

v0.4 nombra `DATABASE_URL` como si apuntara a un solo lugar. Ya son tres.

| Entorno | Dónde | Para qué | Quién la toca |
|---|---|---|---|
| **Local** | contenedor de `compose.yml` | iterar migraciones, smoke tests | cada uno la suya |
| **Compartido** | RDS `database-1`, base `fraud` | integración: mis tablas, su dashboard | los dos |
| **Producción** | no existe todavía | el despliegue final | el CD |

Dos precisiones que salieron de crearla:

- La base es **`fraud`**, no la que RDS provisiona por defecto (`postgres`). Esa
  queda como base de mantenimiento; mezclarla con datos de aplicación estorba en
  restores y permisos.
- Las extensiones son **por base de datos**, no por cluster: `CREATE EXTENSION
  vector` corre dentro de `fraud`.

**Resolución**: §1.4 deja de hablar de "la base" y enumera los entornos. El local
no desaparece al existir el compartido: se itera en local, se integra en
compartido.

### 1.8 — Precedencia de acciones cuando dos políticas aplican

14 transacciones del dataset satisfacen dos políticas a la vez (`FP-02;FP-05` es
la más común). Cuando las acciones prescritas difieren hay que elegir una, y el
Arbiter y el ground truth tienen que usar **la misma regla**, o la comparación es
injusta.

**Resolución**: gana la más restrictiva —
`BLOCK` > `ESCALATE_TO_HUMAN` > `CHALLENGE` > `APPROVE`.

Ya implementada en `scripts/build_ground_truth.py`. Va al contrato como parte de
la semántica de `DecisionType`.

### 1.9 — Idempotencia del seed: upsert, con `--reset` explícito

§2.6 anota que sembrar sobre la base compartida dejó de ser inocuo. El diseño del
script sí es de esta rama.

**Resolución**: `ON CONFLICT DO UPDATE` por defecto; `TRUNCATE ... CASCADE` detrás
de un flag.

`ON CONFLICT DO NOTHING` se descartó por ser la opción que *parece* más segura y
es la peor: si el dataset se regenera y el seed vuelve a correr, no pasa nada, la
base conserva las filas viejas y uno cree que recargó. Fallo silencioso justo en
el dato que sostiene todas las métricas.

El upsert es la versión por fila del principio que ya rige el nodo persistidor:
*un reintento sustituye, no acumula*. Que los casos existentes no se corrompan
cuando un perfil cambia ya está garantizado porque `customer_snapshot` es JSONB
congelado, no FK.

El modo destructivo existe pero arrastra `cases` por el FK, y por eso es explícito.

---

## 2. Abiertas — bloquean la redacción de v0.5

### 2.1 — ~~¿`usual_channel` singular o lista?~~ → **decidida: singular**

No era un artefacto del generador: lo fuerza la cardinalidad. `Channel` tiene dos
valores. Una lista tendría un elemento —idéntico al singular— o los dos, y
entonces FP-06 ("canal nuevo con monto alto") **nunca puede dispararse**: la
política muere. Una lista de 2 sobre 2 posibles es una tautología.

Se revisa el día que `Channel` crezca (ATM, POS, API). Ese es el disparador.

### 2.2 — Fuga temporal en el historial

Con las políticas de secuencia, `transactions` cumple **doble función**: fuente de
casos e historial que los agentes consultan. El agente de secuencias **debe**
filtrar `timestamp < timestamp de la transacción analizada`, no solo "reciente",
o vería el futuro. Es un requisito de corrección; si el harness no lo respeta, sus
métricas salen optimistas.

**Resolución: invariante de persistencia (§7), no frontera de API.** Al dashboard
no le importa, así que no toca §2. Toda consulta de historial lleva
`WHERE timestamp <= :as_of`, donde `as_of` es el timestamp de la transacción bajo
análisis, **nunca `now()`**. El `<=` incluye la transacción actual, que es lo
correcto para contar velocidad.

Se hace cumplir en un solo punto: una función de repositorio por la que pasan
todas las consultas de ventana. Un invariante que depende de que cada autor lo
recuerde no es un invariante.

El ground truth ya lo respeta: en una ráfaga de cuatro, solo la cuarta lleva la
etiqueta de FP-03. Cuando llegó la primera, el patrón no existía.

> Por qué importa: en producción esto es imposible —el futuro no está en la tabla
> cuando llega el caso—, así que un agente que no filtre **funciona bien en
> producción y solo falla en evaluación**, inflando sus propias métricas.

### 2.3 — ¿`CaseSummary` gana `risk_score`?

La cola HITL hoy muestra `decision` y `confidence`. Para triaje, ordenar por
riesgo es más útil que por confianza: el analista quiere ver primero lo más
sospechoso, no lo más incierto.

No se decidió al redactar v0.4 —se dejó fuera para no ampliar el alcance sin
discutirlo—. Es una columna en una proyección plana, barata en cualquier momento.

### 2.4 — ~~Ground truth incompleto~~ → **resuelta: lo producimos nosotros**

Premisa caída: el equipo de banca se retiró del curso. El generador y el catálogo
pasaron a ser nuestros, así que las etiquetas dejaron de ser una petición
bloqueante y se volvieron una decisión de diseño.

`data/ground_truth.csv` tiene una fila por cada una de las 7 000 transacciones,
con `expected_policies`, `expected_decision`, `fraud_group_id` e `is_closing`.
Archivo aparte, no columnas de `transactions.csv`: **el sistema bajo evaluación
nunca ve las etiquetas**.

De los tres puntos originales:

- **FP-08** (antes mal numerada como FP-09) queda **resuelta**. Decía "promedio de
  su segmento" y solo existía el del cliente. Se agregó `segment` al perfil, con
  multiplicadores que separan las distribuciones; el promedio del segmento es una
  consulta acotada por moneda.
- **FP-10** (antes mal numerada como FP-11) queda **fuera del alcance**, con una
  razón mejor que la original. No es que falten etiquetas: su evidencia es
  búsqueda web real, no reproducible entre corridas. *Una política cuya evidencia
  no es reproducible no es evaluable en un harness.* Eso va a Limitaciones del
  entregable 7 y a Recomendaciones del 10.
- **El sesgo de las etiquetas humanas** sigue igual: `human_resolutions` solo
  recibe casos escalados —los ambiguos por construcción—. Ese ground truth no es
  intercambiable con `ground_truth.csv` y no debe mezclarse al medir.

**Alcance final: 10 de 11 políticas** (FP-01…FP-09 y FP-11).

### 2.5 — Fórmula de `base_confidence` y `risk_score`

v0.4 define **qué significan** y **en qué dirección se mueven**; no define los
pesos por severidad, la función de agregación ni el delta máximo que el Arbiter
puede aplicar. Eso vive dentro de `evidence_aggregation` y necesita el catálogo de
`code`, que no existe.

No toca el schema: `scoring_version` ya está previsto justamente para que la
fórmula pueda cambiar sin invalidar lo persistido.

### 2.6 — Reglas de convivencia sobre la base compartida

Con la base compartida, tres operaciones dejan de ser locales y pasan a afectar al
otro. El esquema es mío —poseo el dominio—, pero el efecto lo siente el dashboard.

- **Migraciones.** Las corrí desde mi laptop para desbloquear el arranque. Eso fue
  un **bootstrap**, no el procedimiento: §1.2 dice que el CD las invoca como Job de
  pre-deploy. Mientras ese CD no exista, alguien las corre a mano y conviene fijar
  quién y con qué aviso.
- **`downgrade`.** Es la única operación de esta lista que destruye trabajo ajeno.
  Nadie la ejecuta sobre la compartida sin avisar.
- **Seed.** Sembrar deja de ser "poblar mi local": un seed que solo inserta falla
  al segundo intento por clave duplicada, y uno que trunca borra los casos que el
  dashboard estaba mostrando. El diseño del script es de la rama de dataset; la
  coordinación —quién siembra y cuándo— es frontera.

### 2.7 — Dos roles de base de datos: migrar y servir

Hoy hay un solo rol, el master de RDS, y es `rds_superuser`. Migrar necesita DDL;
servir tráfico solo necesita DML. Con un rol único, un bug de la app puede
ejecutar un `DROP TABLE`.

Separarlos convierte una variable de entorno en dos: `DATABASE_URL` para el
runtime, `MIGRATION_DATABASE_URL` para el Job de pre-deploy. Toca §1.2 y §1.4.

No urge en la compartida —datos sintéticos, reconstruibles—. Sí antes de producción.

### 2.8 — Exposición de red de la base compartida

La instancia es `publicly accessible`: cualquiera con el hostname llega al 5432, y
como AWS publica sus rangos, el escaneo es continuo e independiente de que el
hostname se conozca. Los datos son sintéticos y el esquema se reconstruye con
`alembic upgrade head`, así que el daño posible es molestia y factura, no pérdida.

Es decisión de infraestructura —territorio de mi compañero—, pero es frontera y
por eso queda escrita: o el security group se limita a nuestras IPs, o el contrato
reconoce explícitamente que la base compartida es un entorno desechable.

---

## 3. Hallazgos que **no** tocan el contrato

Van al repaso de etapa. Se anotan acá para no perderlos.

- **Cero aristas condicionales** en el grafo: `DECIDED` vs `PENDING_HUMAN` es un
  valor de `status` que escribe un mismo nodo, no una bifurcación.
- **Atomicidad del superstep**: si un nodo paralelo lanza, se pierden también los
  aportes de sus hermanos y el grafo aborta. Verificado con un grafo mínimo. De
  ahí que los nodos de evidencia **nunca lancen**.
- **Reintentos adentro del nodo**, no vía `RetryPolicy`: son incompatibles, porque
  un nodo que captura su excepción nunca deja que la política dispare.
- **Sin checkpointer**: solo cubriría la muerte del proceso, más barato con una
  consulta sobre casos estancados en `ANALYZING`. Recomendación del entregable 10.
- **Dependencias de runtime por `context_schema`**, no por import global: tres
  nodos necesitarán la base (perfil, secuencias, persistencia) y el import global
  ataría cualquier import del módulo a que haya base configurada.
- **Un test no es dueño de la base**: contar filas globalmente lo vuelve
  dependiente del orden de ejecución. Filtrar siempre por la clave del caso.
- **Postgres 18 movió el directorio de datos** dentro de la imagen: de
  `/var/lib/postgresql/data` a `/var/lib/postgresql`. Con el mount viejo el
  contenedor arranca y muere. Y cruzar una versión mayor exige
  `docker compose down -v`: los directorios de datos no son compatibles entre
  mayores.
- **El master de RDS es `rds_superuser`**, así que `CREATE EXTENSION vector` corre
  desde la migración `c558fd490ae6` sin aprovisionamiento previo. La enmienda que
  se anticipaba —sacar la extensión de las migraciones— no hizo falta. Revive solo
  si algún día se migra con un rol sin privilegios (§2.7).
- **`pg_available_extensions` reporta disponible, no instalada.** Verificar que
  una extensión existe se hace contra `pg_extension`.
- **Las variables exportadas contaminan `docker compose`.** Recrear el contenedor
  desde una terminal con las variables de la nube exportadas hizo que `initdb`
  creara el rol `postgres` en vez de `fraud`. El síntoma fue `password
  authentication failed`, porque Postgres oculta si el rol existe cuando la
  autenticación es por password. Recrear siempre desde terminal limpia.
