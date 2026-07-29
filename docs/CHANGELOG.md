# Changelog — Contrato de Interfaz

Qué cambió entre versiones de `contrato_de_interfaz.md` y por qué. El documento
vivo tiene siempre la versión vigente; su encabezado dice cuál es.

Para recuperar el texto completo de una versión anterior:

```bash
git show contrato-v0.3:docs/contrato_de_interfaz.md
```

> Las versiones 0.1 y 0.2 son anteriores a que el contrato entrara a control de
> versiones: solo sobreviven como entradas de este changelog.

---

## [No publicado]

Enmiendas acumuladas hacia v0.4 en [`enmiendas_pendientes.md`](enmiendas_pendientes.md).
Bloqueada por una decisión abierta: dónde aterrizan `agent_errors`,
`base_confidence` y `confidence_rationale`.

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
