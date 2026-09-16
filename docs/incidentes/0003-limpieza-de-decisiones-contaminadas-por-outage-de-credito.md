# Incidente 0003 — limpieza de decisiones contaminadas por los outages de credenciales

**Fecha de la limpieza**: 2026-09-16. **Ventana contaminada**: 2026-09-14 a
2026-09-15, coincidente con el incidente 0001 (fuga de crédito Anthropic) y
el incidente 0002 (claves desactualizadas en GCP).

No es un incidente nuevo — es la consecuencia visible, en el dato de
producción, de los incidentes 0001 y 0002: cada transacción real que el
usuario corrió mientras las credenciales de Anthropic/Gemini estaban
inválidas o sin crédito quedó registrada como `ESCALATE_TO_HUMAN`, inflando
la tasa de escalamiento que ve cualquiera que entre al dashboard.

## Mecanismo de contaminación

`decision_arbiter` (`graph/nodes.py:636-653`) tiene un `try/except` propio
alrededor de la llamada al juez Anthropic — no cubierto por `@degrades`
porque, a diferencia de los nodos de evidencia, acá una falla del proveedor
tiene que forzar el resultado más conservador, no perder el resultado de
nodos hermanos. Cuando el proveedor no responde (crédito agotado o clave
revocada), el nodo cae al piso determinístico y persiste
`ESCALATE_TO_HUMAN` con el mismo texto fijo, siempre:

```
"proveedor de juicio no disponible: se escala con el piso deterministico"
```

Ese texto exacto es lo que permite distinguir una decisión contaminada de
una genuina — no el rango de fechas, que sólo corrobora.

## Clasificación (confirmada contra la API en vivo, sin tocar la base directo)

35 casos totales, 15 `ESCALATE_TO_HUMAN`:

- **10 contaminados** — mismo `confidence_rationale` exacto de arriba,
  todos entre 2026-09-14 07:22 y 2026-09-15 05:41 (ventana de los
  incidentes 0001/0002):

  | case_id | transaction_id | created_at |
  |---|---|---|
  | `135b14c5-53e7-4e54-a06b-87a6efecd4cf` | `LIVE-t1281-1789450874605` | 2026-09-15 05:41 |
  | `aebb94bd-13bc-486e-98ce-75a0f6155dd9` | `LIVE-t1012-1789450342872` | 2026-09-15 05:32 |
  | `9d6738a7-5025-46ce-9d90-5acffb40a056` | `LIVE-t1125-1789450312266` | 2026-09-15 05:31 |
  | `b91fe144-f7a8-4bf3-a234-3ab266cd335c` | `LIVE-approve-1789405263541` | 2026-09-14 17:01 |
  | `78c07c6d-c0c1-4b70-917c-947b766a8ee4` | `LIVE-t1249-1789405239948` | 2026-09-14 17:00 |
  | `cb29daf1-4164-4996-bada-09014d669efd` | `LIVE-t1125-1789404999622` | 2026-09-14 16:56 |
  | `5f3873ea-d48c-4235-80ea-d56c993245be` | `LIVE-t1165-1789404948949` | 2026-09-14 16:55 |
  | `b747d23b-c11c-459d-9489-3d7e51f06c5f` | `LIVE-escalate-1789370568963` | 2026-09-14 07:22 |
  | `50cc88b4-1174-420f-a372-0859695f7efe` | `LIVE-escalate-1789370537609` | 2026-09-14 07:22 |
  | `01fc13f7-9e71-4fca-bb86-cfb49f657a5c` | `LIVE-challenge-1789370526158` | 2026-09-14 07:22 |

- **5 genuinos** — razonamiento propio, no el texto de arriba, todos antes
  de la ventana (2026-09-07 a 2026-09-11): incluyen los dos casos de vitrina
  del dashboard (`T-5816`, `T-1313`), que no se tocaron.

## Cadena de borrado

`decisions.case_id` → FK a `cases.case_id` con `ondelete="CASCADE"`
(`db/models/decision.py:22-25`), y de ahí en cascada a `signals` y
`agent_errors`. `cases.transaction_id` → FK a `transactions.transaction_id`
**sin** `ondelete` (`db/models/case.py:28-31`): `Transaction` es el padre,
no cascada. Orden: borrar `cases` primero (cascada automática hacia abajo),
después `transactions`.

## Ejecución

Script local (`docs/temp/cleanup_contaminados.py`, gitignored, no
commiteado, corrido por el usuario en su propia terminal para que
`DATABASE_URL` de producción nunca entrara a la conversación con el
agente). Por cada uno de los 10 casos: valida que `transaction_id` y
`confidence_rationale` sigan matcheando la tabla de arriba (aborta todo si
no), escribe un respaldo JSON completo de los 10 registros antes de tocar
nada, y recién entonces:

```sql
DELETE FROM cases WHERE case_id = ANY(%s);        -- cascada a decisions/signals/agent_errors
DELETE FROM transactions WHERE transaction_id = ANY(%s);
```

## Verificación (post-ejecución, vía API pública, ambas nubes)

| | Azure | GCP |
|---|---|---|
| Total de casos | 25 | 25 |
| `ESCALATE_TO_HUMAN` | 5 | 5 |
| Casos contaminados restantes | 0 | 0 |
| `T-5816` presente | sí | sí |
| `T-1313` presente | sí | sí |

**Tasa de escalamiento: 15/35 (42.9%) → 5/25 (20%).**

El respaldo JSON de los 10 registros borrados queda en
`docs/temp/backup_casos_contaminados_*.json` (local, gitignored) por si
hace falta auditar el detalle completo más adelante.

## Pendiente

- El mecanismo de contaminación en sí (path 3 de `decision_arbiter`) es
  correcto — es la degradación esperada cuando el proveedor no responde.
  Lo que faltó es un chequeo de integridad que hubiera evitado que datos
  de un outage conocido se mezclaran silenciosamente con datos genuinos;
  no se aborda acá, queda como mejora aparte si vuelve a pasar.
- La tasa de escalamiento del dashboard se calcula client-side sobre
  `GET /cases?limit=200` sin paginación real
  (`dashboard/src/routes/Dashboard.tsx:122-127`) — con 25 casos no es un
  problema hoy, pero es un techo no documentado si el dataset crece.
