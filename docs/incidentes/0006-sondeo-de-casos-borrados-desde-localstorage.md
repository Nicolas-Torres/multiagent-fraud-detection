# Incidente 0006 — el dashboard sondeaba casos borrados desde `localStorage`

**Fecha**: 2026-09-25. **Detectado**: por el usuario, en la consola del
navegador de las dos demos (Azure y GCP), al abrir la web sin ejecutar nada.
No hubo alerta del sistema.
**Impacto**: tráfico inútil contra la API y la base mientras hubiera una
pestaña abierta; con Neon serverless, cada consulta despierta el compute —el
mismo mecanismo de costo del [incidente 0005](0005-costo-de-neon-por-readiness-probe-continuo.md)—.

## Síntoma

Una ráfaga de `GET /api/v1/cases/{id} → 404` apenas carga la página. Los IDs
eran exactamente los casos contaminados que el
[incidente 0003](0003-limpieza-de-decisiones-contaminadas-por-outage-de-credito.md)
borró: `01fc13f7…` y `50cc88b4…` en Azure; `b747d23b…`, `9d6738a7…`,
`aebb94bd…` y `135b14c5…` en GCP.

## Causa raíz

`Transactions.tsx` guarda en `localStorage`
(`ultimo-case-id-por-escenario`) el último `case_id` de cada escenario en vivo,
para mostrar su resultado al volver. La limpieza del 0003 borró esos casos
mirando sólo las cascadas de la base; los navegadores que los habían ejecutado
siguieron guardando sus IDs. `localStorage` es por dominio, por eso cada nube
mostraba los IDs de las corridas hechas en ella.

Tres defectos del cliente lo convirtieron en un costo sostenido:

1. **Sondeo sin salida ante error.** Fila, chip y panel usaban
   `refetchInterval: data?.decision ? false : 3000`. Con 404 nunca hay `data`:
   un caso inexistente se consultaba **cada 3 s** mientras la pestaña estuviera
   abierta — unas 1 200 consultas por hora y por ID.
2. **Reintentos para un error permanente.** El `QueryClient` reintentaba cada
   404 tres veces.
3. **El ID nunca se olvidaba**: el problema se repetía en cada visita.

## Fix

[PR #54](https://github.com/Nicolas-Torres/multiagent-fraud-detection/pull/54)
(`d138483`):

- `api/cases.ts`: `consultarCaso` distingue el 404 con `CasoNoEncontrado`.
- `main.tsx`: un `CasoNoEncontrado` no se reintenta; el resto conserva los 3
  reintentos.
- El sondeo se detiene si la consulta está en error.
- Un `case_id` guardado que la API ya no conoce se borra de `localStorage` y la
  fila vuelve a "Ejecutar".

## Verificación

- `case_id` inventado en `localStorage`, 15 s en la página y una recarga: **una
  sola consulta** en total, la clave se borró y la fila quedó en "—".
- Ejecución real de un escenario: el sondeo llegó al veredicto (APPROVE, 21 s),
  se detuvo ahí y guardó el `case_id` nuevo.

## Aprendizaje

El borrado del 0003 se verificó hacia adentro (cascadas de FK) y no hacia
afuera (quién más guardaba esos IDs), y el sondeo nunca se había probado con un
caso inexistente. Queda como regla en
[`CLAUDE.md`, "Antes de cerrar un cambio"](../../CLAUDE.md): referencias fuera
de la base, estado que sobrevive, caminos de error, costo de lo periódico y
verificación después del deploy.

## Pendiente

Ninguno de los seis incidentes lo detectó una alerta. Los pendientes de
alertado de los incidentes 0001 y 0002 se consolidan acá:

- **Tasa de 4xx por endpoint**, en particular `GET /cases/{id}`: un pico
  sostenido de 404 es este mismo síntoma.
- **Consumo de Neon (CU-hours)** contra la asignación gratuita, antes de que
  llegue el mail del 80 %.
- **Gasto y errores del job `fetch-intel`** (incidente 0001).
- **Nodos degradados en producción** — el "Evidencia incompleta" del
  incidente 0002.
