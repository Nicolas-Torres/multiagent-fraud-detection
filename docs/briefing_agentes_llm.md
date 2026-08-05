# Briefing — próxima etapa: agentes con LLM

**Sistema Multi-Agente de Detección de Fraude · inicialización de chat**

> Documento corto y **hacia adelante**. El estado completo está en
> [`reviews/06-rag-de-politicas.md`](reviews/06-rag-de-politicas.md); esto es lo
> que la etapa siguiente necesita tener a mano y las decisiones que va a tener
> que tomar.
>
> Contrato vigente: **v0.7** (`contrato_de_interfaz.md`). Sin enmiendas
> acumuladas, sin decisiones conjuntas pendientes.

---

## 1. Dónde está el sistema

Un caso entra por `POST /cases`, corre siete supersteps y sale con veredicto,
citas verificables, señales, explicación y cuatro sellos de auditoría. **Sin
LLM en el camino de la decisión**: el veredicto lo produce hoy un árbitro
determinístico.

| Pieza | Estado |
|---|---|
| Motor de reglas, catálogo en Postgres, harness 7 000/7 000 | ✅ |
| RAG de políticas: autorización + descubrimiento | ✅ |
| Árbitro **determinístico** (brazo de control) | ✅ |
| Explicabilidad: auditoría por plantilla, cliente por LLM | ✅ |
| **Debate Agents** (pro-fraude ∥ pro-cliente) | ⬜ stub |
| **Arbiter con LLM** | ⬜ |
| **Threat Intel + `web_search_allowlist`** | ⬜ |
| API FastAPI + HITL | ⬜ |
| CI, imagen, despliegue | ⬜ |

Reparto de veredictos hoy: `APPROVE` 90.7% · `ESCALATE_TO_HUMAN` 4.1% ·
`BLOCK` 3.6% · `CHALLENGE` 1.6%.

---

## 2. Los cinco principios que la etapa siguiente no puede romper

Salieron de etapas anteriores y cada uno tiene un ADR o un acta detrás.

1. **La cita autoriza el veredicto, no lo acompaña.** `citations_internal`
   contiene una cita por cada política que disparó. Se resuelve por identidad
   contra el catálogo, no por búsqueda vectorial (ADR-0011).
2. **Un agente que falla degrada, no aborta.** `@degrades` en los nodos de
   evidencia; `FAILED` es sólo para una excepción no capturada del grafo entero.
   Y **`@degrades` solo no alcanza** cuando un nodo tiene dos caminos con
   garantías distintas: el frágil necesita su propio `try`.
3. **Derivar, nunca escribir.** `owner`, `requires`, `signals`, `evaluable` y los
   cuatro `PolicyState` se calculan al cargar. Guardarlos sería poder
   desincronizarlos (ADR-0007).
4. **Lo que se audita se sella; lo que se genera no se mide con métricas duras.**
   Cuatro ejes de versión en `decisions`; el carril LLM-as-judge está separado
   por ADR-0013.
5. **Los gates determinísticos tienen que dar el mismo número dos veces.**
   `check_policies` y `check_retrieval` no pueden depender de una salida de LLM.

---

## 3. Lo primero que hay que decidir

### 3.1 Qué hace el Arbiter con LLM que el determinístico no hace

El determinístico aplica la precedencia del catálogo y ya reproduce el ground
truth. Si el agéntico sólo lo imita, no hay nada que medir. Las hipótesis
plausibles, y **hay que elegir cuál se prueba**:

- Resolver **evidencia contradictoria** entre los dos Debate Agents.
- **Ajustar la confianza** con justificación auditable —el campo
  `confidence_rationale` existe y hoy siempre es `null`—.
- **Apartarse de la precedencia** cuando el descubrimiento aporta contexto que la
  política no contempla.

El brazo de control ya está construido, así que la comparación del entregable 7
es directa. Lo que falta es la hipótesis.

### 3.2 La cláusula recíproca del invariante

Quedó **deliberadamente fuera** de v0.7: *aprobar exige que no haya disparado
ninguna política*. Convertiría en error el override pro-cliente que un Arbiter con
LLM podría querer hacer con justificación.

Es la decisión que abre esta etapa. Si se adopta, el override deja de ser
representable; si no, hace falta otro mecanismo para que aprobar ignorando FP-03
no pase inadvertido.

### 3.3 Debate: ¿dos llamadas o una?

Los dos agentes corren en paralelo en el superstep 3 y escriben en claves
distintas. Con LLM son dos llamadas por caso, más la del Arbiter, más la de la
explicación: **cuatro por caso**. Con 7 000 transacciones en el harness eso no es
viable, así que hay que decidir el muestreo antes de escribir el nodo — igual que
`check_retrieval` agrupa por combinación de señales para pasar de 7 000 llamadas
a 76.

### 3.4 Proveedor

Dos en uso: **Gemini** para embeddings, **Anthropic** para generación. Los dos
entran por un puerto (`Embedder`, `Narrator`), se inyectan en `GraphContext` y se
pueden reemplazar por un doble sin red. El Arbiter y los Debate Agents necesitan
un tercer puerto o reusar `Narrator` — pero `Narrator` está tipado para redactar,
no para decidir, y ampliarlo invitaría a darle al modelo un rol que no tiene.

---

## 4. Lo que hay que saber para no repetir errores

- **Un LLM nunca nombra una política.** Recibe las citas ya resueltas y los temas
  ya traducidos. Un modelo con permiso de nombrar `policy_id` reintroduce el
  fallo que ADR-0011 cerró.
- **El texto al cliente omite umbrales, ventanas, conteos y códigos.** Explicarle
  la regla al titular es entregársela a quien quizás sea el defraudador. Lo que
  se omite ahí está en `explanation_audit`, que lo lee un analista.
- **`asyncio.to_thread` para todo cliente de proveedor**: son síncronos y
  bloquean el event loop, y con él las ramas hermanas del superstep.
- **El texto que se persiste es prosa plana**, sin markdown.
- **Un generador de artefactos versionados tiene que ser determinista entre
  procesos.** `Table.foreign_key_constraints` es un `set`.
- **Una prueba que no puede fallar es peor que no tenerla.** Ocupa el lugar de la
  que serviría y da confianza falsa.

---

## 5. Deuda abierta que la etapa puede tocar

| Deuda | Dónde |
|---|---|
| `check_retrieval.py` no es gate de CI (necesita índice y caché) | acta 06 §6.4 |
| `SAFE_THEMES` necesita revisión con criterio **legal** | acta 06 §6.5 |
| La costura `GraphContext` ↔ nodos no tiene cobertura de tests | acta 06 §6.3 |
| `logger.exception` produciría 7 000 tracebacks en una caída real | acta 06 §6.5 |
| `web_search_allowlist` sigue sin modelar: espera al Threat Intel | contrato §4 |
| El C4 container hay que revisarlo al cerrar cada etapa | README, tabla de diagramas |

---

## 6. Comandos de arranque

```bash
docker compose up -d && uv run alembic upgrade head && uv run python scripts/seed.py

uv run pytest                                        # 161, sin red ni base
uv run python scripts/check_policies.py --source=db  # 7000/7000
uv run python scripts/smoke_decision.py              # 3 escenarios en DECIDED
```

`GEMINI_API_KEY` y `ANTHROPIC_API_KEY` son opcionales: sin ellas el sistema
decide igual, con el descubrimiento vacío y la explicación por plantilla.

---

## 7. Documentación de referencia

- `contrato_de_interfaz.md` — **v0.7**, las dos fronteras
- `reviews/06-rag-de-politicas.md` — el estado completo de la etapa anterior
- `adr/0011` · `adr/0012` · `adr/0013` — las tres decisiones del RAG
- `adr/0006` · `adr/0007` — brazo de control y políticas como dato
- `docs/diagrams/citacion-interna.drawio` — los dos caminos, de un vistazo
