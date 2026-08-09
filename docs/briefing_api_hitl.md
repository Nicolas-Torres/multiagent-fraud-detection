# Briefing — próxima etapa: API FastAPI + HITL

**Sistema Multi-Agente de Detección de Fraude · inicialización de chat**

> Documento corto y **hacia adelante**. El estado completo está en
> [`reviews/08-llm-agents.md`](reviews/08-llm-agents.md); esto es lo que la
> etapa siguiente necesita tener a mano y las decisiones que va a tener que
> tomar.
>
> Contrato vigente: **v0.9** (`contrato_de_interfaz.md`). Sin enmiendas
> acumuladas, sin decisiones conjuntas pendientes.

---

## 1. Por qué esta etapa y no CI/despliegue

Con `feature/llm-agents` cerrada, los nueve nodos del grafo están todos
implementados: un caso entra con `case_id` y `transaction` sintéticos
(cómo lo hacen los smokes) y sale con veredicto, citas, debate y
explicación. Lo que falta para que el sistema sea *usable* —no sólo
correcto— es la frontera HTTP: hoy no hay forma de crear un caso ni de
resolver uno escalado salvo invocando el grafo directo desde Python.

CI/imagen/despliegue necesita algo que desplegar. El orden natural es
API + HITL primero.

---

## 2. Lo que ya está decidido — el contrato, no esta etapa

A diferencia de Threat Intel o de los agentes con LLM, **el contrato ya
especifica los endpoints** (§2.3, vigente desde v0.2, no una decisión nueva):

| Método | Ruta | Propósito |
|---|---|---|
| `POST` | `/api/v1/cases` | Ingresar transacción, arrancar el grafo en segundo plano |
| `GET` | `/api/v1/cases` | Listar/filtrar la cola HITL |
| `GET` | `/api/v1/cases/{case_id}` | Detalle completo |
| `POST` | `/api/v1/cases/{case_id}/resolution` | Acción del analista sobre un caso `PENDING_HUMAN` |
| `GET` | `/api/v1/policies` | Catálogo con estado de cada política |
| `POST` | `/api/v1/policies` | Alta de política |
| `GET` | `/api/v1/predicates` | Biblioteca de predicados, para el compositor del dashboard |
| `GET` / `GET` | `/health`, `/ready` | Liveness / readiness |

Esta etapa es mayormente **implementación de lo ya acordado**, no diseño desde
cero — la diferencia con las dos etapas anteriores. Eso no la vuelve trivial:
lo que sigue abierto son detalles de implementación que el contrato no baja a
ese nivel.

---

## 3. Dónde está el sistema

| Pieza | Estado |
|---|---|
| Motor de reglas, catálogo en Postgres (Fase 2: archivos versionados), harness 7 000/7 000 | ✅ |
| RAG de políticas: autorización + descubrimiento | ✅ |
| Threat Intel Agent: recolección gobernada + consulta congelada | ✅ |
| Debate ×2 + Arbiter con LLM sobre un piso determinístico | ✅ |
| Evaluación de calidad (DeepEval, no bloqueante) | ✅ |
| **API FastAPI + HITL** | ⬜ **esta etapa** |
| CI, imagen, despliegue | ⬜ |

Todos los W0/W2/W3 del contrato (§7.2) son hoy funciones de Python invocadas
directo desde scripts (`smoke_decision.py`, etc.), no endpoints.

---

## 4. Lo primero que hay que decidir

### 4.1 Cómo arranca el grafo en segundo plano desde `POST /cases`

El contrato ya dice que W0 crea `transactions` + `cases` en `RECEIVED` y
devuelve `202`, y que el grafo corre después, en segundo plano — el nodo
persistidor (W2) no puede usar la sesión del request porque ya devolvió.
Lo que no está decidido: `BackgroundTasks` de FastAPI (más simple, vive y
muere con el proceso) contra una cola real (más resiliente a un restart a
mitad de un caso, más infraestructura). Para un proyecto de este tamaño,
`BackgroundTasks` es probablemente suficiente — pero es una decisión, no un
default a asumir sin nombrarla.

### 4.2 Fase 2 vs Fase 3 del catálogo, y si esta etapa la fuerza

`GET/POST /api/v1/policies` implica leer y escribir el catálogo desde
Postgres. Hoy el catálogo vive en dos JSON versionados
(`data/policies/`, Fase 2 de ADR-0007) y `load_catalog()` los relee en cada
arranque de proceso. Las tablas de Fase 3 (`fraud_policies`, `binding_sets`,
`policy_bindings`) **no existen todavía** — `domain/catalog.py` ya las
menciona en un comentario como la forma a la que se migrará. Implementar
`POST /api/v1/policies` tal como está en el contrato empuja esa migración a
esta etapa, aunque no sea sobre agentes.

### 4.3 Autenticación de los endpoints HITL

El contrato no especifica autenticación — es terreno del "compañero"
(infraestructura) según §0, pero alguien tiene que decidir si esta etapa la
incluye o la deja como TODO explícito. Un endpoint que resuelve casos
(`POST .../resolution`) sin autenticar es una superficie real si el sistema
llega a desplegarse, aunque sea un proyecto académico.

### 4.4 Cómo se prueba una API sin duplicar el trabajo de los smokes

Los smokes actuales (`smoke_decision.py`, etc.) invocan el grafo directo.
Falta decidir el equivalente para la API: ¿tests de integración con
`TestClient` de FastAPI contra una base de test, o smokes nuevos que hagan
HTTP real contra un servidor levantado? Mismo criterio de siempre —los gates
determinísticos no dependen de red ni LLM— aplicado a una capa nueva.

---

## 5. Los principios que la etapa no puede romper

1. **W2 sigue siendo el único nodo que escribe a `decisions`/`signals`/`agent_errors`.**
   La API no le agrega un segundo escritor.
2. **`transaction_id` es la clave de idempotencia de `POST /cases`** (§2.4 del
   contrato): mismo `transaction_id` = mismo caso, `200` sin re-correr el
   grafo; nuevo = `202`.
3. **`PENDING_HUMAN` es terminal para el grafo, no un `interrupt()`.** La
   resolución es flujo HTTP aparte (W3), no una reanudación del grafo.
4. **La cuarta guarda de W2 (ADR-0016) no cambia**: si un caso llega a la API
   con `FAILED`, es un bug del Arbiter, no un estado que el endpoint deba
   intentar reparar.
5. **Los gates determinísticos siguen sin tocar red ni LLM.** Una prueba de
   la API que dependa de que el Arbiter responda de una forma específica
   hereda el mismo problema que §2 de `08-llm-agents.md` ya documentó para
   los smokes.

---

## 6. Lo que hay que saber para no repetir errores

- **W2 no puede usar la sesión del request**: ya devolvió `202` cuando el
  grafo termina. Necesita su propia sesión (`AsyncSessionLocal`), como ya
  hacen todos los smokes.
- **`WindowsSelectorEventLoopPolicy` sólo en el entry point de la app**, no
  en cada script — con un servidor FastAPI real, hay un único punto de
  entrada donde fijarla, a diferencia de los scripts sueltos que hoy la
  configuran cada uno.
- **Un gate no compara con igualdad estricta contra la salida de un
  componente no determinístico que puede apartarse en una dirección
  conocida** (`08-llm-agents.md` §2) — aplica a cualquier test de la API que
  toque un caso real end-to-end.
- **El modelo/proveedor no es variable de entorno**: sólo la clave. Sigue
  valiendo para cualquier configuración que la API exponga.

---

## 7. Deuda abierta (heredada, no de esta etapa)

| Deuda | Dónde |
|---|---|
| `fundamentacion_del_debate` con scores bajos en la corrida real, sin diagnóstico | acta 08 §6.3 |
| Golden set en 7 casos, no ~15; sin caso de agente degradado | acta 08 §6.1, §6.2 |
| `SAFE_THEMES` necesita revisión con criterio **legal** | acta 06 §6.5 |
| `arbiter_prompt_version` / `debate_prompt_version` sin sellar | acta 08 §6.4 |
| `check_retrieval.py` no es gate de CI | acta 06 §6.4 |

---

## 8. Después de esta etapa

**Dashboard del analista (frontend)** — el reto pide explícitamente
"web App (Backend + Frontend)", y hasta ahora sólo se construyó el backend.
El contrato §3 ya especifica en detalle qué consume: cola, detalle de caso y
vista de políticas — no es diseño desde cero, es la contraparte visual de lo
que esta etapa expone. Después de esa, **CI, imagen y despliegue**, para
tener algo completo que desplegar.

---

## 9. Comandos de arranque

```bash
docker compose up -d && uv run alembic upgrade head && uv run python scripts/seed.py

uv run pytest                                        # 260, sin red ni base
uv run python scripts/check_policies.py --source=db  # 7000/7000
uv run python scripts/smoke_decision.py              # 5 escenarios en DECIDED/PENDING_HUMAN
```

`GEMINI_API_KEY` y `ANTHROPIC_API_KEY` son opcionales para los gates
determinísticos: sin ellas el sistema decide igual, con el descubrimiento
vacío, el debate y el juicio del Arbiter degradados a su respaldo, y la
explicación por plantilla.

---

## 10. Documentación de referencia

- `contrato_de_interfaz.md` — **v0.9**; **§2** especifica endpoints y schemas completos
- `reviews/08-llm-agents.md` — estado completo de la etapa anterior
- `adr/0007` — fases del catálogo (2: archivos, 3: tablas — relevante para §4.2)
- `adr/0016` — el piso del Arbiter, relevante para cualquier endpoint que exponga `decision`/`confidence_rationale`
