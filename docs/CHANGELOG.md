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

Enmiendas hacia la próxima versión en [`enmiendas_pendientes.md`](enmiendas_pendientes.md),
acumuladas en la etapa de dataset y seed.

Corrección de fondo pendiente de redactar: **la numeración de políticas usada
hasta ahora estaba corrida** a partir de la octava. El catálogo real es
`FP-01`…`FP-11` sin huecos. Afecta a `briefing_dataset.md` y a
`enmiendas_pendientes.md` §1.3, ambos ya anotados.

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
