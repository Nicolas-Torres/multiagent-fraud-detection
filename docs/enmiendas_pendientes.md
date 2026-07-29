# Enmiendas pendientes — Contrato de Interfaz v0.4

**Estado**: acumulando. Se consolida en `contrato_de_interfaz_v0_4.md` al cerrar
la etapa del grafo (hoy es un esqueleto: la topología existe, los agentes no).

> Documento de trabajo. Predecesor vigente: `contrato_de_interfaz_v0_3.md`.

---

## 1. Maduras — decididas, listas para redactar

| # | Enmienda | Toca | Origen |
|---|---|---|---|
| 1 | Invariante de citación | §2.5 `Decision` | diseño del Arbiter |
| 2 | `signals` no está en "orden de producción" | §2.5 `Decision` | verificado en smoke test |
| 3 | `agent_route`: orden por superstep, no total | §2.5 `Decision` | verificado en smoke test |
| 4 | `PENDING_HUMAN` es estado terminal del grafo | §5 decisiones cerradas | se descartó `interrupt()` |
| 5 | Cuatro puntos de escritura y qué ve el dashboard en cada estado | §7 nuevo apartado | derivado de los observadores |

### 1.1 — Invariante de citación

> Ningún **veredicto autónomo** sin respaldo interno. Diferir a un humano no es
> un veredicto.

Formalmente: `citations_internal` es no vacío siempre que
`decision != ESCALATE_TO_HUMAN`.

Dos capas, sin solapamiento:

- **Arbiter** (regla de negocio): sin citas no puede emitir `APPROVE`,
  `CHALLENGE` ni `BLOCK` → degrada a `ESCALATE_TO_HUMAN`. La ausencia de
  respaldo *es* la razón para llamar al humano.
- **Nodo de persistencia** (guarda): la misma condición como aserción. Si
  dispara, el Arbiter tiene un bug — y una guarda que repara es una guarda que
  esconde bugs, así que levanta.

Sin la excepción para `ESCALATE_TO_HUMAN`, un caso donde el RAG no recupera
nada no tendría salida: no podría aprobar, ni bloquear, ni escalar.

**Consecuencia para el dashboard**: puede asumir citas internas no vacías en
todo caso `DECIDED`. Es una garantía, no una probabilidad.

### 1.2 — `signals` no está en "orden de producción"

v0.3 §2.5 promete *"orden de producción preservado"*. Es falso: tres agentes
emiten señales desde ramas paralelas, y el orden entre ramas de un mismo
superstep no es el de declaración.

Verificado: se declaró `transaction_context` primero y la ruta lo devolvió
tercero.

**Redacción propuesta**: el orden lo fija Evidence Aggregation con un criterio
determinístico y documentado (no "de producción"). Es requisito de
reproducibilidad para el harness del entregable 7, no cosmética.

### 1.3 — `agent_route`: orden por superstep, no total

Mismo hecho, otro campo. El orden **entre** supersteps está garantizado;
**dentro** de uno es estable entre corridas pero no significa precedencia.

**Redacción propuesta**: documentar que `agent_route` es una secuencia de
supersteps aplanada, y que la adyacencia dentro de un grupo no implica orden
causal. Un auditor que lea la ruta como cadena causal se equivocaría.

### 1.4 — `PENDING_HUMAN` es estado terminal del grafo

El `interrupt()` de LangGraph se descartó: el `Command(resume=...)` no
transportaba nada y cobraba un thread suspendido y filas de checkpointer por
cada caso pendiente. El grafo termina en el nodo de persistencia; la resolución
del analista es flujo HTTP puro.

La máquina de estados de §2.1 **no cambia**. Cambia cómo se alcanza
`RESOLVED`: lo escribe el endpoint, no el grafo reanudado.

**Puerta abierta**: el día que exista `REQUEST_INFO`, o que la resolución deba
regenerar la explicación al cliente, eso es un **segundo grafo corto** invocado
por el endpoint — no el primero reanudado. Para entonces el estado original ya
está archivado en las tablas.

### 1.5 — Cuatro puntos de escritura

Cada uno existe porque un observador externo necesita ver algo en ese instante.
Si nadie mira, no hay escritura.

| | Quién escribe | Qué | Observador |
|---|---|---|---|
| **W0** | endpoint `POST /cases` | `transactions` + `cases` en `RECEIVED` | sin esto no hay `case_id` que devolver |
| **W1** | wrapper del background task | `status = ANALYZING` | distingue "aceptado" de "corriendo" |
| **W2** | nodo de persistencia (único en el grafo) | `decisions` + `signals` + `decided_at` + `status`, una transacción | la cola HITL |
| **W3** | endpoint `POST /resolution` | `human_resolutions` + `RESOLVED` | el analista |

**Garantía derivada, que el dashboard puede asumir:**

| `status` | `decision` | `human_resolution` |
|---|---|---|
| `RECEIVED`, `ANALYZING` | `null` | `null` |
| `DECIDED`, `PENDING_HUMAN` | **completa** (nunca parcial) | `null` |
| `RESOLVED` | completa | presente |
| `FAILED` | puede ser `null` | `null` |

No hay estados intermedios visibles: W2 escribe todo en un commit.

`FAILED` no lo escribe ningún nodo — un agente caído degrada la decisión, no la
aborta. `FAILED` es para una excepción no capturada del grafo entero, y la
escribe el wrapper de W1, que es quien tiene el `try`.

**Idempotencia de W2**: `DELETE FROM decisions WHERE case_id = :id` (la cascada
barre `signals`) + `INSERT`. Semántica de **reemplazo del agregado**, no
"asegurar que estas filas existan". Un reintento sustituye, no complementa.

---

## 2. Abierta — bloquea la redacción de v0.4

### 2.1 — Tres campos del `State` sin destino

El `State` produce tres valores relevantes para auditoría que **no tienen dónde
aterrizar**: ni columna en `decisions`, ni campo en el contrato, ni salida al
dashboard.

| Campo | Qué contiene | Por qué un auditor lo quiere |
|---|---|---|
| `agent_errors` | qué agente falló y por qué | *"se aprobó sin inteligencia externa porque ese agente estaba caído"* justifica o invalida la decisión a posteriori |
| `base_confidence` | el score determinístico, antes del Arbiter | sin él no se puede medir **cuánto** movió el Arbiter la confianza |
| `confidence_rationale` | la justificación del ajuste | v0.3 §2.5 promete confianza *"ajustable por el Arbiter con justificación"* y no define dónde vive esa justificación |

Los tres son el mismo problema: la trazabilidad que el contrato promete en
prosa no tiene representación en el schema.

**Opciones sobre la mesa** (no decidido):

| Opción | Costo | Consecuencia |
|---|---|---|
| Columnas nuevas en `decisions` | migración + campos en `Decision` | consultable; alimenta métricas del entregable 6 |
| Todo dentro de `explanation_audit` | cero | narrativo; no se puede agregar ni graficar |
| JSONB único de metadatos de ejecución | una columna | flexible, pero es exactamente lo que la regla §7.2 llama "lo que el sistema mide" y manda a tabla |

Se decide al modelar el nodo de persistencia (`feature/decision-persistence`).
**Hasta entonces v0.4 no se redacta**, o habría que redactar v0.5 dos semanas
después por una sola fila.

---

## 3. Hallazgos de implementación que **no** tocan el contrato

Van al repaso de etapa, no al contrato. Se anotan acá para no perderlos.

- **Cero aristas condicionales.** `DECIDED` vs `PENDING_HUMAN` es un valor de
  `status` que escribe un mismo nodo, no una bifurcación del grafo. El diseño
  original anticipaba edges condicionales; no hicieron falta.
- **Atomicidad del superstep.** Si un nodo de un superstep paralelo lanza, se
  pierden también los aportes de sus hermanos y el grafo aborta. Verificado con
  un grafo mínimo en `scripts/smoke_degradation.py`. Consecuencia: los nodos de
  evidencia **nunca lanzan** — capturan y devuelven `agent_errors`.
- **Reintentos adentro del nodo, no `RetryPolicy`.** Son incompatibles: si el
  nodo captura su propia excepción, LangGraph nunca ve la falla y la política no
  dispara. `RetryPolicy` queda solo para los nodos fatales (Arbiter,
  Explainability, persistencia).
- **Sin checkpointer.** Sin `interrupt()` y con los nodos capturando su falla,
  solo cubriría la muerte del proceso — más barato con una consulta sobre casos
  estancados en `ANALYZING`. Queda como recomendación del entregable 10.
- **El diagrama de topología se autogenera**: `build_graph().get_graph()
  .draw_mermaid()`. No se puede desincronizar del código.

---

## 4. Nota de proceso

`contrato_de_interfaz_v0_3.md` y los `repaso_*.md` **no están versionados en el
repo**. El contrato es el artefacto de frontera que valida el compañero (§1) y
que define lo que consume el dashboard (§2–§4): debería vivir en `docs/` junto
a este archivo, no fuera de control de versiones.
