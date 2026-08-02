# ADR-0001: Postgres con pgvector como única base de datos

- **Estado**: aceptado
- **Fecha**: 2026-07-16

## Contexto

El sistema necesita persistir cuatro cosas de naturaleza distinta:

1. **Datos relacionales**: transacciones, casos, decisiones, señales, cola HITL.
2. **Vectores**: embeddings de las políticas de fraude para el RAG interno.
3. **Audit trail**: allowlist de búsqueda web gobernada, resoluciones humanas.
4. **Estado de ejecución**: el checkpointer de LangGraph, si se habilita.

El equipo son dos personas y el despliegue lo hace el compañero. Cada servicio
adicional es una pieza más de infraestructura que aprovisionar, monitorear y
explicar en la defensa.

El corpus vectorial es pequeño y estático: un puñado de políticas de fraude
versionadas, no millones de documentos.

## Decisión

Una sola instancia de **PostgreSQL 17 con la extensión pgvector**
(`pgvector/pgvector:pg17`), que cubre los cuatro usos.

La extensión se habilita en la primera migración de Alembic
(`CREATE EXTENSION IF NOT EXISTS vector`, idempotente), antes de cualquier tabla.

## Alternativas descartadas

**Base vectorial dedicada (Pinecone, Qdrant, Chroma) junto a Postgres.**
Mejor rendimiento de índice a gran escala, pero introduce un segundo servicio,
un segundo backup, un segundo secreto y consistencia eventual entre el caso y
sus embeddings. El corpus no justifica ninguno de esos costos.

**SQLite + FAISS en disco.** Arranque más simple, pero SQLite no soporta acceso
concurrente escritor desde múltiples réplicas, y el despliegue en nube con
réplicas es requisito del entregable 5.

**Postgres sin pgvector, con similitud calculada en la aplicación.** Evita la
extensión a costa de traer todos los embeddings a memoria en cada consulta.
Funciona con diez políticas y no escala a ninguna otra cosa; el ahorro es una
línea de migración.

## Consecuencias

**A favor**

- Una sola `DATABASE_URL`. El contrato operativo (§1.4) queda con una variable
  de entorno menos y el compañero aprovisiona un solo recurso.
- Consistencia transaccional entre un caso y sus embeddings: no hay ventana en
  la que el caso exista y el vector no.
- El checkpointer de LangGraph, si se habilita, vive en la misma base.

**En contra, aceptado a sabiendas**

- pgvector rinde por debajo de un motor dedicado a partir de cierto volumen. Con
  este corpus es irrelevante, pero es la primera pieza a revisar si el sistema
  creciera. Va a Recomendaciones (entregable 10).
- La imagen `pgvector/pgvector:pg17` no es la oficial de Postgres. Es la que
  mantiene el proyecto pgvector; hay que fijarla explícitamente en el compose y
  documentarlo para el CD.
- Si el checkpointer se habilita, LangGraph crea sus propias tablas. `alembic
  check` como gate de CI las verá como tablas sin modelo → habrá que excluirlas
  con `include_object` en `migrations/env.py`.
