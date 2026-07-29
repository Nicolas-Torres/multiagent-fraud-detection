# ADR-0002: Regla para elegir entre JSONB, tabla relacional y ARRAY

- **Estado**: aceptado
- **Fecha**: 2026-07-23

## Contexto

El contrato de API define `Decision` con cuatro estructuras anidadas:
`signals` (lista de objetos), `citations_internal` y `citations_external`
(listas de objetos), `agent_route` (lista de strings) y `debate` (objeto de dos
campos).

Postgres ofrece tres formas de guardarlas, y decidir caso por caso lleva a
inconsistencias. Hacía falta un criterio, no cuatro decisiones sueltas.

## Decisión

| Si el contenido… | Va a |
|---|---|
| es un escalar homogéneo, se lee siempre completo, no existe sin su dueño | `ARRAY` |
| tiene forma anidada, se produce y se archiva, se lee entero junto al caso | `JSONB` |
| tiene identidad, ciclo de vida propio, o el sistema lo **mide** | tabla |

Destilado: **JSONB para lo que el sistema produce y archiva; relacional para lo
que el sistema mide.**

Aplicación:

- `signals` → **tabla**. Son la unidad de evaluación del harness (entregable 7)
  y del monitoreo de drift (entregable 6). El índice en `code` es su razón de
  ser.
- `citations_internal` / `citations_external` → **JSONB**. Narrativa de
  auditoría: se leen enteras junto al caso, nunca solas.
- `agent_route` → **`varchar[]`**. Secuencia de escalares donde el orden es la
  información.
- `debate` → **dos columnas `Text`**. Objeto de dos campos fijos que no va a
  crecer; JSONB solo agregaría indirección. Se recompone en la frontera con una
  property del ORM.

## Alternativas descartadas

**Todo JSONB, una columna por estructura.** Migración más simple y esquema
flexible. Pero el `GROUP BY code` que el monitoreo necesita sobre `signals`
pasaría a ser un desempaquetado en cada consulta, y el harness compararía
señales esperadas contra producidas sin poder indexarlas.

**Todo relacional, una tabla por estructura.** Consistente, pero crea dos tablas
de citas que solo se leen junto a su caso, nunca por separado y nunca agregadas.
Serían tablas sin ninguna consulta propia: el JOIN sería puro costo.

**`ARRAY` para las citas.** Postgres soporta arrays de tipos compuestos, pero
evolucionar el tipo compuesto exige migración, y el schema de las citas es justo
lo que puede crecer. JSONB deja ese schema en Pydantic.

## Consecuencias

**A favor**

- El criterio se reutiliza: cualquier estructura nueva del contrato se clasifica
  sin volver a discutir.
- `signals` queda consultable e indexada, que era el requisito real.

**En contra, aceptado a sabiendas**

- **JSONB no significa "sin schema"**: significa que el schema vive en Pydantic
  en vez de en el DDL. `InternalCitation`, `ExternalCitation` y `DebateSummary`
  son el contrato de forma de esas columnas, de ida y de vuelta. Nada en la base
  lo hace cumplir.
- Escribir Pydantic a JSONB exige `model_dump(mode="json")`: en modo Python,
  `HttpUrl` y `datetime` no son serializables por psycopg.
- La mutación in situ no se detecta. `obj.lista.append(x)` no marca el objeto
  como sucio ni en `ARRAY` ni en JSONB; hay que reasignar la colección completa.
- `debate` como dos columnas planas obliga a una property en el ORM para
  recomponer el objeto valor en la frontera. Es indirección barata, pero existe.
