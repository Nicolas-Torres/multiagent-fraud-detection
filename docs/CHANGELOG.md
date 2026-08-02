# Changelog — Contrato de Interfaz

Qué cambió entre versiones de `contrato_de_interfaz.md` y por qué. El documento
vivo tiene siempre la versión vigente; su encabezado dice cuál es.

Para recuperar el texto completo de una versión anterior:

```bash
git show contrato-v0.4:docs/contrato_de_interfaz.md
```

> Las versiones 0.1 y 0.2 son anteriores a que el contrato entrara a control de
> versiones: solo sobreviven como entradas de este changelog.

---

## [No publicado]

Sin enmiendas acumuladas. Las próximas se anotan en
[`enmiendas_pendientes.md`](enmiendas_pendientes.md).

---

## [0.5] — Dataset, seed e invariante temporal

Diez enmiendas, salidas de convertir el dataset en instrumento de evaluación y de
poner en marcha la base compartida.

| # | Enmienda | Toca | Por qué |
|---|---|---|---|
| 1 | Muere el supuesto `America/Lima` | §2.5, §2.7 | El dataset tiene siete países. Interpretar la ventana de un cliente de Madrid como hora de Lima la corre siete horas y evalúa otra franja. Afecta al 86% de los clientes. |
| 2 | `CustomerBehavior` gana `currency` y `timezone` | §2.5 | La moneda es atributo de la **cuenta**, no del país de la compra: sin ella, "3× el promedio" mezcla unidades. La zona no se puede derivar del país —US y MX abarcan varias—. |
| 3 | `CustomerBehavior` gana cinco campos más | §2.5 | `usual_channel`, `account_creation_date`, `last_profile_update`, `daily_limit` y `segment` habilitan FP-06, FP-08, FP-09 y FP-11, que sin ellos no tenían insumo. |
| 4 | Precedencia entre políticas concurrentes | §2.2 | 14 transacciones satisfacen dos políticas a la vez. Si el Arbiter y el ground truth usaran órdenes distintos, el harness mediría la discrepancia entre reglas, no la calidad del sistema. |
| 5 | Índices compuestos de historial | §7.1 | Cuatro políticas evalúan secuencias. Dos ejes de acceso —cliente y dispositivo— porque FP-03 no filtra por cliente: un dispositivo usado con varias cuentas **es** la señal. |
| 6 | 🆕 §7.7 El invariante *as-of* | §7.7 | Un agente que consulte historial sin acotar ve el futuro. En producción es imposible de violar, así que el bug **solo aparece en evaluación** — y hacia arriba, inflando el recall. |
| 7 | `merchant_blacklist` entra al modelo | §7.1 | Primera tabla de gobernanza. PK natural con baja lógica: la historia no se pierde porque el caso congela su evidencia en `signals`. |
| 8 | `DATABASE_URL` cambia de forma | §1.4 | RDS exige TLS (`?sslmode=require`) y el password viaja percent-encoded: dentro de una URL es un tramo delimitado, no un campo, y cualquier carácter estructural lo parte. |
| 9 | Postgres destino sube a 18 | §1.4 | Mientras local y nube difieran, "pasa en local" deja de ser evidencia de "pasa en la nube". |
| 10 | Tres entornos de base de datos, no uno | §1.4 | v0.4 hablaba de "la base" como si fuera una. Son tres: local para iterar, compartido para integrar, producción sin existir todavía. |

**Retirada durante la etapa**: `Transaction` iba a ganar `issuer_bank`. Era el
insumo de FP-10 y de nada más; con esa política fuera de alcance sería una columna
sin consumidor. `Transaction` no cambia en v0.5.

**Corrección de fondo**: la numeración de políticas usada hasta v0.4 estaba
corrida a partir de la octava —el análisis leyó los comentarios del generador en
vez del catálogo—. El catálogo real es `FP-01`…`FP-11` **sin huecos**: no falta
`FP-08` ni existe `FP-12`. El alcance implementado pasó de 9/11 a **10/11**.

Detalle en [`reviews/04-dataset-y-seed.md`](reviews/04-dataset-y-seed.md) y en
los ADR 0003, 0004 y 0005.

---

## [0.4] — Grafo, scoring y trazabilidad de ejecución

Todas las enmiendas salieron de construir el grafo de agentes y su nodo
persistidor, y de verificar el round-trip contra Postgres.

### Cambiado

- **`confidence` cambia de significado.** Deja de ser un score derivado de las
  señales y pasa a medir **seguridad en el veredicto autónomo**. La distinción
  es necesaria: la sospecha es monótona en las severidades, la confianza tiene
  forma de U —máxima con muchas señales graves *y* con ninguna, mínima con
  señales contradictorias—. Una función monótona no puede producir las dos.
- **El orden de `signals` ya no es "de producción".** Tres agentes emiten desde
  ramas paralelas y el orden entre ramas de un mismo superstep no es el de
  declaración. Lo fija Evidence Aggregation con un criterio determinístico, que
  es requisito de reproducibilidad para el harness del entregable 7.
- **`agent_route` se precisa**: es el rastro de los **agentes** —no de todos los
  nodos— y es una secuencia de supersteps aplanada. La adyacencia dentro de un
  grupo no implica precedencia causal.
- **El invariante de citación pasa de calidad a estructural.** Las políticas
  internas *prescriben una acción*, no describen riesgo: el veredicto sale de la
  política que aplica, no de umbralizar un score. La cita no acompaña la
  decisión, la **autoriza**.
- **HITL sin `interrupt()`.** `PENDING_HUMAN` es estado terminal del grafo y la
  resolución es flujo HTTP puro. El `Command(resume=...)` no transportaba nada y
  cobraba un thread suspendido y filas de checkpointer por cada caso pendiente.
  La máquina de estados no cambia; cambia quién escribe la transición.

### Agregado

- **`Decision.risk_score`** — sospecha determinística. Ordena la cola y alimenta
  el monitoreo de drift; **no** decide, y el Arbiter no puede ajustarlo: si un
  LLM pudiera moverlo, dejaría de servir para medir.
- **`Decision.base_confidence`** y **`confidence_rationale`** — la confianza
  antes del ajuste y la justificación del delta. La confianza híbrida que el
  contrato prometía desde v0.2 pasa de promesa a schema. `rationale = null`
  significa una sola cosa: no hubo ajuste.
- **`Decision.scoring_version`** — sin ella los scores de casos viejos dejan de
  ser reproducibles al cambiar la fórmula, y el entregable 7 pide explícitamente
  comparación de enfoques: va a haber más de una versión.
- **`Decision.degraded_agents`** — qué evidencia faltó al decidir. Un agente que
  falla degrada la decisión, no la aborta.
- **Tabla `agent_errors`** (§7.2) — el detalle de las fallas, frontera interna.
  Tabla y no JSONB por el mismo motivo que `signals`: el sistema las mide.
- **§7.3 Los cuatro puntos de escritura** y la garantía derivada de qué ve el
  dashboard en cada `status`. El grafo escribe **una sola vez**, con semántica de
  **reemplazo del agregado**: un reintento sustituye, no complementa. Hace falta
  porque `signals.id` es BIGSERIAL sin UNIQUE y una segunda escritura duplicaría
  en silencio.
- **Guardas explícitas en el punto de escritura** que hacen cumplir lo que §2.5
  promete. Levantan, no reparan: una guarda que repara esconde el bug.
- **`LOG_LEVEL` gobierna el echo de SQL** de SQLAlchemy (§1.4).

---

## [0.3] — Persistencia cerrada y verificada

Todas las enmiendas salieron de modelar `Case`/`Decision` de punta a punta y de
verificar el round-trip contra Postgres. Ninguna es cosmética.

### Cambiado

- **`CaseDetail.customer` pasa a nullable.** Un cliente nuevo sin perfil es un
  escenario válido —y de los más sospechosos—. Rechazarlo ciega al sistema ante
  el caso que más importa.
- **`HumanResolution` se parte en `HumanResolutionIn` y `HumanResolutionRead`.**
  `resolved_at` lo acuña el servidor: si viniera en el request, un analista
  podría antedatar su propia resolución en una cola de auditoría.
- **`CaseSummary` se documenta como proyección plana.** v0.2 la escribía con
  rutas anidadas (`decision.decision`). Es un objeto plano con nombres propios,
  construido por un factory explícito que tolera casos sin decisión.
- **`Decimal` se serializa como string JSON.** Un número JSON es un float IEEE y
  perdería centavos. Afecta a `amount` y `usual_amount_avg`: el dashboard debe
  parsearlos como string.

### Agregado

- **`Decision.decided_at`.** Con `cases.created_at` da la latencia del pipeline:
  métrica de producción del entregable 6, prácticamente gratis.
- **`Page[T]` con forma explícita**: `items`, `total`, `limit`, `offset`. v0.2 la
  nombraba sin definirla.
- **§7 Modelo de persistencia**: las seis tablas y las decisiones
  JSONB-vs-relacional que v0.2 dejó abiertas. Ver ADR-0002.
- **`alembic check` como gate de CI.** Retorna distinto de cero si un modelo
  cambió sin migración correspondiente.

---

## [0.2] — Consolidado para reunión de equipo

### Cambiado

- **`POST /cases` recibe solo la transacción.** `CustomerBehavior` se recupera
  dentro del grafo (Behavioral Pattern Agent), ya no viene en el request.
- **Allowlist de búsqueda web: de variable de entorno a tabla gobernada** con
  audit trail. Es dato de gobernanza (mutable, administrado por un humano), no
  config de infraestructura.
- **Migraciones fuera del entrypoint.** La imagen soporta
  `alembic upgrade head`; el CD lo invoca como Job de pre-deploy. Con N réplicas,
  meterlo en el arranque normal daría N migraciones concurrentes.

### Agregado

- **Idempotencia por `transaction_id`.** Un reintento de la pasarela devuelve el
  caso existente con `200`, no crea uno nuevo.
- **Reparto CI/CD explícito.** CI es mío (build → GHCR), CD es del compañero. La
  imagen versionada en GHCR es el punto de hand-off.
- **Requisitos de empaquetado**: tags inmutables (nunca `latest`),
  `linux/amd64`, usuario no-root, `.dockerignore`.
- **`/ready` separado de `/health`.** Liveness comprueba que el proceso vive;
  readiness comprueba que Postgres responde.

### Confirmado

- Cálculo de confianza **híbrido** (determinístico desde señales + ajuste del
  Arbiter).
- Notificación al dashboard por **polling** en v1; WebSocket queda como mejora.

---

## [0.1] — Versión inicial

Primer trazado de las dos fronteras: contrato operativo (con infraestructura) y
contrato de API (con el dashboard). Estableció la separación entre `status`
(etapa del pipeline) y `decision` (veredicto), y entre `case_id` (UUID del
servidor) y `transaction_id`.

> Redactada antes de que el contrato entrara a control de versiones. Los cambios
> listados en 0.2 describen implícitamente su contenido.
