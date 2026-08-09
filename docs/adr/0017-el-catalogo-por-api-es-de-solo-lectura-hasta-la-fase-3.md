# ADR-0017: el catálogo por API es de solo lectura hasta la Fase 3

- **Estado**: aceptado
- **Fecha**: 2026-08-09

## Contexto

El contrato especifica `GET /api/v1/policies` y `POST /api/v1/policies` desde
v0.2 (§2.3): el catálogo con estado de cada política, y el alta de una nueva,
para el compositor del dashboard. Nunca se implementó porque hasta esta etapa
no había frontera HTTP en absoluto.

El catálogo hoy vive en **Fase 2** de ADR-0007: dos JSON versionados en
`data/policies/`, releídos por `load_catalog()` en cada arranque de proceso.
La **Fase 3** —tablas `fraud_policies`, `binding_sets`, `policy_bindings`— está
nombrada en `domain/catalog.py` como el destino futuro, pero no existe: ninguna
migración la creó, y nada la necesitó hasta ahora.

`GET /api/v1/policies` es trivial sobre la Fase 2: `PolicyCatalog` ya tiene
exactamente la forma que el endpoint necesita devolver —`policy_id`, estado,
acción, versión—. `POST /api/v1/policies` no lo es: escribir una política
nueva en runtime necesita un destino seguro para escrituras concurrentes y con
registro de quién la dio de alta y cuándo, que es exactamente lo que un
archivo no da y una tabla sí — el mismo motivo por el que `merchant_blacklist`
y `web_search_allowlist` son tablas y no archivos.

## Decisión

**Esta etapa implementa `GET /api/v1/policies` de solo lectura sobre el
catálogo de Fase 2. `POST /api/v1/policies` queda sin implementar.**

`GET` reutiliza `load_catalog()` —el mismo catálogo que ya construye
`GraphContext`— sin agregar una fuente de datos nueva. `POST` no responde con
un `501` ni con una implementación parcial: la ruta simplemente no existe
todavía, y el cliente recibe `404`. La migración a Fase 3 —tablas, versionado
de bindings, quién puede dar de alta, validación de condiciones— se decide y
ejecuta en una etapa aparte, cuando haya una necesidad real de altas
dinámicas por API y no sólo la promesa del contrato.

## Alternativas descartadas

**Forzar la Fase 3 en esta etapa.** Acoplaría una migración de esquema no
trivial —con sus propias preguntas de diseño, ninguna sobre la frontera
HTTP— a una etapa que se supone es sobre ingerir casos y resolverlos, no
sobre el modelo del catálogo. Ampliaría el alcance sin necesidad real
todavía: nada en el reto exige altas de políticas por API antes de que exista
un dashboard que las use.

**`POST /api/v1/policies` escribiendo directo al archivo JSON.** Un alta
concurrente con otro proceso leyendo el mismo archivo —el grafo, en medio de
un caso— es una condición de carrera real, y el archivo no tiene forma de
registrar autoría ni fecha sin reinventar a mano lo que una tabla da gratis.

**Responder `501 Not Implemented`.** Sugiere una implementación a medias o
rota. La ausencia de la ruta es una descripción más honesta del estado real:
el endpoint no existe, no que exista y falle.

## Consecuencias

**Se gana** que la etapa de API + HITL se queda enfocada en lo que la nombra
—ingestar transacciones, exponer la cola, resolver casos escalados— sin
arrastrar una migración de catálogo no relacionada.

**Se paga** que el contrato prometía `POST /api/v1/policies` desde v0.2 y esta
etapa no lo cumple. Queda declarado como deuda explícita en el acta de
cierre, no como un olvido silencioso.

**El día que la Fase 3 se implemente**, `GET /api/v1/policies` cambia de
fuente —archivo a tabla— sin cambiar de forma: `PolicyRead` no se toca, sólo
el repositorio detrás. El endpoint de lectura no hay que reescribirlo, sólo
reconectarlo.
