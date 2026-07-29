# Repaso — Etapa "Modelos de dominio"
**Sistema Multi-Agente de Detección de Fraude · handoff de continuidad**
 
> Documento de cierre de etapa. Destila lo decidido y construido en
> `feature/domain-models`, para retomar en el chat dedicado al **`State` del grafo**
> con el contexto ya condensado.
>
> Predecesor: `repaso_fundacion_bd.md`. Contrato vigente: `contrato_de_interfaz_v0_3.md`.
 
---
 
## 1. Qué se cerró en esta etapa
 
La **capa de datos completa**: seis tablas en Postgres y toda la frontera pública
de schemas que FastAPI necesita para sus `response_model`.
 
| Entidad | Schema | ORM | Migración | Verificado |
|---|---|---|---|---|
| `Transaction` | ✅ | ✅ | `b2a8d4bf4ee2` | ✅ |
| `CustomerBehavior` | ✅ | ✅ | `97de35e4842b` | ✅ |
| `Case` | ✅ | ✅ | `ac3bc6c8573d` | ✅ |
| `Decision` | ✅ | ✅ | `ac3bc6c8573d` | ✅ |
| `Signal` | ✅ | ✅ | `ac3bc6c8573d` | ✅ |
| `HumanResolution` | ✅ | ✅ | `ac3bc6c8573d` | ✅ |
 
**Head de Alembic**: `ac3bc6c8573d`. Cadena lineal desde `c558fd490ae6` (pgvector).
 
**Pendiente de modelar**: `web_search_allowlist` (§4 del contrato). Las tablas del
checkpointer de LangGraph las crea LangGraph, no Alembic.
 
---
 
## 2. El patrón que se repitió, entidad por entidad
 
```
1. Enum(s) compartidos si aplica       → enums.py
2. Schema Pydantic (frontera)          → schemas/
3. Modelo ORM (Mapped/mapped_column)   → db/models/ (+ registrar en __init__.py)
4. alembic revision --autogenerate     → LEER la migración
5. alembic upgrade head                → verificar con \d+
```
 
El paso 4 no es ceremonia: leer la migración antes de aplicarla atrapó cosas como
`sa.ARRAY` genérico donde debía ir `postgresql.ARRAY`.
 
---
 
## 3. Las decisiones jugosas y su porqué
 
### 3.1 JSONB vs relacional vs ARRAY
 
La regla que se destiló y que aplica a lo que venga:
 
| Si el contenido… | Va a |
|---|---|
| es un escalar homogéneo, se lee siempre completo, no existe sin su dueño | **`ARRAY`** |
| tiene forma anidada, se produce y se archiva, se lee entero junto al caso | **`JSONB`** |
| tiene identidad, ciclo de vida propio, o el sistema lo **mide** | **tabla** |
 
> **JSONB para lo que el sistema produce y archiva; relacional para lo que el
> sistema mide.**
 
- `signals` → tabla, porque son la **unidad de evaluación** del harness (entregable 7)
  y del monitoreo de drift (entregable 6). El índice en `code` es la razón de ser.
- `citations_internal/external` → JSONB, narrativa de auditoría.
- `agent_route` → `varchar[]`, secuencia donde el orden es la información.
- `debate` → dos columnas `Text`; objeto de dos campos fijos, JSONB solo agregaría
  indirección. Se recompone en la frontera con una property.
### 3.2 Congela lo mutable, referencia lo inmutable
 
`cases.customer_snapshot` es JSONB nullable, **no** un FK a `customer_behaviors`.
 
Una transacción es un evento inmutable → referenciarla es seguro. Un perfil muta →
un FK haría que un caso de enero mostrara el perfil de marzo. Auditoría rota.
 
Corolario: **no hay FK de `transactions.customer_id`**. Un cliente nuevo sin perfil
debe poder insertar transacciones; ese escenario no es un error, es el más sospechoso.
 
### 3.3 `Decision` como tabla propia, con PK compartida
 
`decisions.case_id` es PK **y** FK a `cases.case_id` → 1:1 sin constraint extra.
 
Nueve columnas nulables que solo tienen sentido juntas no son nueve campos
opcionales: son **un objeto valor ausente**. Eso se modela con una fila que existe o
no existe. Además deja barata la opción de re-análisis (entregable 7): quitar la
restricción y agregar PK surrogate.
 
Mismo patrón en `human_resolutions`.
 
### 3.4 `Decimal` para dinero, `float` para el score
 
`Decimal` existe porque los montos se suman y deben cuadrar al centavo. Un
`confidence` no se suma ni se audita contablemente; `Numeric` ahí sería cargo cult.
 
Visible en la frontera: `"amount": "9500.00"` (string) vs `"confidence": 0.42`
(número). Pydantic serializa `Decimal` como string a propósito.
 
### 3.5 Validar, no mutar
 
Un validator que **transforma** el dato en silencio es peor que uno que rechaza.
Excepción: transformaciones **sin pérdida** (`to_upper` en códigos de país — `"pe"`
y `"PE"` son el mismo país). Cuantizar `850.5033 → 850.50` **destruye** información
y por eso no vive en el schema: el productor cuantiza explícitamente.
 
### 3.6 Dónde vive la normalización de formato
 
`"08-20"` → `(8, 20)` y `"PE"` → `["PE"]` viven en el **script de seed**, no en el
schema. `CustomerBehavior` nunca llega por HTTP: su frontera es el dataset, no el
API. Un adaptador por fuente; el dominio recibe datos canónicos.
 
### 3.7 Extraer tipos compartidos: dos consumidores reales
 
`schemas/types.py` nació con `CountryCode` y `Money` (dos consumidores cada uno) y
creció con `Confidence` al llegar `Decision`. `CurrencyCode` sigue inline: un solo
consumidor.
 
El caso instructivo: `Money` casi se extrae antes de tiempo con una distinción falsa
entre monto y promedio. Extraer temprano habría horneado esa distinción o la habría
borrado por presión de reuso.
 
Nombrar por **concepto de negocio**, no por forma: `CountryCode`, nunca `Str2`.
 
---
 
## 4. Convenciones nuevas fijadas
 
- **Sin `CheckConstraint`**: `--autogenerate` y `alembic check` tienen un punto ciego
  con ellos → migración manual obligatoria y falsa seguridad si se desincronizan.
  Con un solo escritor, el boundary cubre las rutas reales. (Distinto de la Opción A
  de enums, que se decidió por otro motivo: los enums crecen.)
- **Nunca `nullable=False` explícito**: en ORM 2.0 sale del tipo `Mapped[...]`.
- **`lazy="selectin"` en todas las relaciones**: obligatorio en async; el lazy
  loading por defecto lanza `MissingGreenlet`. Se sobreescribe por consulta cuando
  la cola no necesita los hijos.
- **`model_dump(mode="json")`** al escribir Pydantic a JSONB.
- **PK surrogate**: UUID cuando la identidad **viaja al cliente**; entero
  autoincremental cuando es interna (y preserva orden de inserción gratis).
- **Properties en el ORM** para recomponer objetos valor (`Decision.debate`,
  `Case.customer`). Devuelven `dict`, no Pydantic → `db/` no importa de `schemas/`.
- **Factory explícito** (`CaseSummary.from_case`) en vez de `AliasPath`: la
  proyección de la cola es una decisión de contrato, y tolera `decision is None`.
- **`Read` hereda de `In`** cuando los campos son idénticos; se separan el día que
  diverjan.
- **`alembic check` como gate de CI**: retorna ≠ 0 si un modelo cambió sin migración.
### Footguns documentados
 
| Trampa | Detalle |
|---|---|
| Mutación in situ | `obj.lista.append(x)` no marca sucio en `ARRAY` ni JSONB → reasignar |
| `Field(max_length=2)` en `list[str]` | valida el largo de la **lista**, no del elemento |
| `now()` de Postgres | es `transaction_timestamp()`: todo el commit comparte instante |
| `onupdate=func.now()` | se dispara en Python; un `UPDATE` en SQL crudo no lo toca |
| `SQLEnum` | persiste el **nombre** del miembro (`MEDIUM`), la frontera expone el **valor** (`"medium"`) |
 
---
 
## 5. Verificación de la etapa
 
**Smoke test** (`scripts/smoke_read.py`): siembra dos casos —uno completo, uno
mínimo—, los relee en una **sesión nueva** (fuerza el `SELECT` real, no el identity
map) y valida contra los schemas `Read`. Confirmó:
 
1. `debate` sale anidado desde dos columnas planas
2. `usual_countries: ["PE"]` sembrado como `["pe"]` → `to_upper` sobrevive el
   round-trip por JSONB
3. `url` como string y `retrieved_at` con offset → `model_dump(mode="json")` cumple
4. `signals` en orden de inserción, sin exponer `id`
5. `server_default` de los tres timestamps leídos correctamente
6. El caso mínimo devuelve `customer`, `decision`, `human_resolution` en `null` sin
   explotar, y `CaseSummary` degrada limpio
> Cuando llegue `pytest` (entregable 5), `sembrar()` se vuelve una fixture y los seis
> puntos se vuelven seis `assert`. El trabajo no se tira: se reordena.
 
---
 
## 6. Mapa de archivos al cierre
 
```
multiagent-fraud-detection/
├── docker-compose.yml
├── alembic.ini
├── migrations/
│   ├── env.py
│   └── versions/        # c558 · b2a8 · 97de · ac3b (head)
├── scripts/
│   └── smoke_read.py                     # smoke test de la capa Read
├── pyproject.toml / uv.lock / .python-version
└── src/multiagent_fraud_detection/
    ├── enums.py                          # Channel, CaseStatus, DecisionType,
    │                                     # HumanAction, Severity
    ├── config/settings.py
    ├── db/
    │   ├── base.py
    │   ├── session.py
    │   └── models/
    │       ├── __init__.py               # registra los 6 modelos
    │       ├── transaction.py
    │       ├── customer_behavior.py
    │       ├── case.py                   # + property customer
    │       ├── decision.py               # + property debate
    │       ├── signal.py
    │       └── human_resolution.py
    └── schemas/
        ├── types.py                      # CountryCode, Money, Confidence
        ├── transaction.py                # TransactionIn / TransactionRead
        ├── customer_behavior.py          # ...In / ...Read
        ├── decision.py                   # objetos valor + SignalRead/DecisionRead
        ├── human_resolution.py           # ...In / ...Read
        ├── case.py                       # CaseCreated/CaseDetail/CaseSummary
        └── pagination.py                 # Page[T]
```
 
---
 
## 7. Qué sigue: el `State` del grafo
 
**La tentación a resistir: `State` no es `CaseDetail`.** Tienen forma parecida y
propósito opuesto.
 
| | `CaseDetail` | `State` |
|---|---|---|
| Qué es | frontera pública | memoria de trabajo interna |
| Ciclo de vida | se construye una vez, al responder | muta en cada nodo |
| Quién lo persiste | la sesión de SQLAlchemy | el **checkpointer** de LangGraph |
| Un campo `null` significa | "no aplica" | "todavía no" |
| Contiene | lo que el dashboard debe ver | + chunks crudos del RAG, resultados descartados por el allowlist, contadores de reintento, errores parciales por agente |
 
Preguntas abiertas para esa conversación:
 
1. **Forma del `State`**: `TypedDict` vs Pydantic. Reducers (`Annotated[list, add]`)
   para los campos que los nodos acumulan en paralelo.
2. **Qué se proyecta a las tablas, y cuándo.** El `State` acumula evidencia parcial;
   las seis tablas solo deben ver el resultado consolidado. ¿Un nodo terminal que
   persiste, o escrituras incrementales por nodo?
3. **`agent_route`**: ¿lo construye el `State` acumulando, o se deriva del trace de
   LangSmith?
4. **HITL**: `interrupt()` de LangGraph + la cola en `cases.status = PENDING_HUMAN`.
   Cómo se reconcilian el checkpointer y la tabla — son dos registros del mismo hecho.
5. **Confianza híbrida**: dónde vive el score determinístico desde señales, y cómo
   el Arbiter lo ajusta con justificación auditable.
6. **Nodos = agentes**: los ocho del reto, edges condicionales, y qué pasa cuando un
   agente falla (¿`FAILED`, o decisión degradada con señal de "evidencia incompleta"?).
### Después del grafo
 
RAG (chunk + embed de políticas, pgvector ya habilitado) → API FastAPI → HITL
(interrupt + cola) → harness de evaluación (entregable 7) → CI (entregable 5).
 
---
 
## 8. Documentación asociada
 
- `contrato_de_interfaz_v0_3.md` — contrato completo (operativo + API + persistencia).
- `repaso_fundacion_bd.md` — etapa anterior.
- Diagramas draw.io de esta etapa:
  - **Modelo de datos** — las 6 tablas, relaciones y la frontera JSONB/relacional.
  - **Ciclo de vida del caso** — máquina de estados + qué tabla se escribe en cada transición.
  - **C4 Container actualizado** — construido vs. pendiente.
- Sistema de documentación: **C4** (Context → Container → Component → Code) como
  columna estructural, más vistas dinámicas. Se documenta incrementalmente, al
  cerrar cada etapa.
 