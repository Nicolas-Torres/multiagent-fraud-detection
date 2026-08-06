# multiagent-fraud-detection

Sistema multi-agente de detección de fraude. Motor de reglas determinístico, RAG
de políticas sobre pgvector, grafo de LangGraph, decisión trazable con sellos de
auditoría.

**Conversación en español. Commits y código en inglés.**

---

## Comandos

```bash
docker compose up -d && uv run alembic upgrade head && uv run python scripts/seed.py

uv run pytest                                        # sin red ni base
uv run python scripts/check_policies.py --source=db  # gate: 7000/7000
uv run alembic check                                 # gate: modelo sin migración
uv run python scripts/export_data_model_diagram.py --check   # gate: modelo sin diagrama
```

Dependencias con `uv`, nunca `pip`. Windows + Git Bash.

---

## Flujo de trabajo

- GitHub Flow: `feature/*` → PR → `main`, con **squash merge**.
- Commits intermedios: **sólo el subject line** de Conventional Commits, sin
  cuerpo. Ej: `feat(db): add threat_indicators governance table`.
- Descripción del PR: **máximo 6 líneas**.
- Las decisiones de diseño se resuelven **antes** de implementar y quedan en un
  ADR bajo `docs/adr/`. Un ADR aceptado es inmutable: si cambia, se escribe otro
  y el viejo se marca *reemplazado*.
- **Leer toda migración autogenerada antes de aplicarla.** No es ceremonia: ha
  atrapado `sa.ARRAY` genérico donde debía ir `postgresql.ARRAY` e índices que
  ninguna consulta usa.
- No aplicar migraciones ni correr `--reset` sin confirmación explícita.

---

## Convenciones que se apartan del default

**SQLAlchemy**
- **Nunca `nullable=False` explícito**: en ORM 2.0 la nulabilidad sale del tipo
  `Mapped[...]`.
- **Sin `CheckConstraint`**: `--autogenerate` y `alembic check` tienen un punto
  ciego con ellos, y un constraint desincronizado da falsa seguridad.
- **Enums**: `native_enum=False`, sin CHECK. La validación vive en Pydantic y en
  la capa in-Python de SQLAlchemy.
- **`lazy="selectin"` en todas las relaciones**: obligatorio en async, el lazy
  loading por defecto lanza `MissingGreenlet`.
- **PK surrogate**: UUID cuando la identidad viaja al cliente; entero
  autoincremental cuando es interna.

**Dominio**
- **Derivar, nunca escribir.** Lo que se puede calcular al cargar no se guarda:
  guardarlo sería poder desincronizarlo.
- **Validar, no mutar.** Un validator que transforma en silencio es peor que uno
  que rechaza. Excepción: transformaciones sin pérdida (`to_upper` en códigos de
  país).
- **`Decimal` para dinero, `float` para scores.** Los montos se suman y deben
  cuadrar al centavo; un score no se audita contablemente.
- **La cita autoriza el veredicto, no lo acompaña.** El veredicto sale de la
  política que aplica, nunca de umbralizar un score.

**Grafo**
- **`@degrades` es obligatorio en los nodos de evidencia.** Si un nodo de un
  superstep paralelo lanza, se pierden también los resultados de sus hermanos.
- **`@degrades` solo no alcanza** cuando un nodo tiene dos caminos con garantías
  distintas: el frágil necesita su propio `try`.
- **`asyncio.to_thread` para todo cliente síncrono de proveedor**: bloquea el
  event loop y con él las ramas hermanas del superstep.
- El estado es `TypedDict` con `total=False`. Reducers **sólo** en las claves
  multi-escritor.

**Proveedores y sellos**
- **El modelo y el prompt viven en código, nunca en `env`.** Sólo la clave es
  variable de entorno: uno configurable por entorno podría cambiarse sin que suba
  la versión sellada, y entonces los sellos de la decisión mentirían.
- **Un LLM nunca nombra un `policy_id`.** Recibe las citas ya resueltas y los
  temas ya traducidos.
- **El texto al cliente omite umbrales, ventanas, conteos y códigos.**
  Explicarle la regla al titular es entregársela a quien quizás sea el
  defraudador.
- **El texto que se persiste es prosa plana**, sin markdown.

**Pruebas**
- **Una prueba que no puede fallar es peor que no tenerla**: ocupa el lugar de la
  que serviría y da confianza falsa.
- **Un doble de prueba lleva su propia versión**, para que no pueda confundirse
  con dato real.
- Los gates determinísticos no pueden depender de una salida de LLM ni de la red.

---

## Footguns verificados

| Trampa | Detalle |
|---|---|
| Mutación in situ | `obj.lista.append(x)` no marca sucio en `ARRAY` ni JSONB → reasignar la colección |
| `Field(max_length=2)` en `list[str]` | valida el largo de la **lista**, no del elemento |
| `now()` de Postgres | es `transaction_timestamp()`: todo el commit comparte instante |
| `onupdate=func.now()` | se dispara en Python; un `UPDATE` en SQL crudo no lo toca |
| `SQLEnum` | persiste el **nombre** del miembro (`MEDIUM`); la frontera expone el **valor** (`"medium"`) |
| Escribir Pydantic a JSONB | usar `model_dump(mode="json")`: en modo Python, `HttpUrl` y `datetime` no son serializables |
| psycopg3 async en Windows | `WindowsSelectorEventLoopPolicy` sólo en el entry point de la app |
| Generadores de artefactos | tienen que ser deterministas entre procesos: `Table.foreign_key_constraints` es un `set` |

---

## Documentación

- `docs/contrato_de_interfaz.md` — las dos fronteras. **Es la fuente de verdad**
  de schemas, endpoints y persistencia.
- `docs/enmiendas_pendientes.md` — enmiendas acumuladas para la próxima versión.
  Se vacía al publicar, nunca hay dos.
- `docs/adr/` — decisiones con su razón y sus alternativas descartadas.
- `docs/reviews/` — cierre de cada etapa, en orden.
- `docs/catalogo_de_politicas.md` — las once políticas y su estado.
- `docs/requisitos/` — enunciado y rúbrica. **De un tercero, no se editan.**
- `docs/trazabilidad.md` — qué evidencia cubre cada ítem de la rúbrica, y los
  desvíos declarados frente al enunciado.

Al cerrar una etapa: acta en `docs/reviews/`, enmiendas al contrato, `CHANGELOG.md`,
tabla de estado del README, y regenerar los diagramas.