# Briefing — próxima etapa: Dashboard del analista (frontend)

**Sistema Multi-Agente de Detección de Fraude · inicialización de chat**

> Documento corto y **hacia adelante**. El estado completo está en
> [`reviews/09-api-hitl.md`](reviews/09-api-hitl.md); esto es lo que la
> etapa siguiente necesita tener a mano y las decisiones que va a tener que
> tomar.
>
> Contrato vigente: **v0.10** (`contrato_de_interfaz.md`). Sin enmiendas
> acumuladas, sin decisiones conjuntas pendientes.

---

## 0. Temas previos:
Ya tienes migrations/, scripts/ y alembic.ini como hermanos de raíz que no son parte del paquete Python. Una carpeta dashboard/ se suma a esa lista; no es una reestructuración, es un directorio más. No hay que tocar pyproject.toml, ni el layout src/, ni nada del backend.

Y ahí sí los ejes se acoplan: con dashboard/ como hermano, un Dockerfile multi-etapa (node:22-alpine → npm run build → COPY --from del dist/) te da una imagen, una URL, cero CORS.
Recomendación: Dashboard/ como hermano de raíz, toolchain propio, build multi-etapa, StaticFiles montado después de las rutas del API. Una imagen para tu compañero, una URL para la demo del entregable 8.

Considerar lo siguiente:
1. Contrato de datos antes que código. Genera tipos con openapi-typescript. Claude Code alucina endpoints y formas de payload cuando no tiene tipos reales; con ellos el porcentaje de código que compila a la primera sube muchísimo.
2. Fixtures reales, no lorem ipsum. Un fixtures.json con 25–30 transacciones que cubran los cuatro veredictos (APPROVE / CHALLENGE / BLOCK / ESCALATE_TO_HUMAN) y los seis estados. Sin datos concretos el diseño sale genérico: tablas vacías, cards de "métrica" sin sentido. Con datos, el layout se adapta a lo que de verdad tienes que mostrar.
3. Loop visual. Esto es lo grande. Sin capacidad de ver lo que construye, Claude Code escribe UI a ciegas. Agrega Playwright como MCP local:
    ```
    claude mcp add playwright npx @playwright/mcp@latest
    ```
   Con eso navega tu dev server, toma screenshots y se autocorrige. Es la diferencia entre "hizo algo que funciona" y "hizo algo que se ve bien".
4. build estático: Vite + React + TypeScript + Tailwind + shadcn/ui, con TanStack Query para el fetching y Recharts para los gráficos.
5. trace del razonamiento: 
   1. Operación: tabla filtrable de transacciones con veredicto y estado → al hacer clic, panel de detalle con el recorrido por el grafo LangGraph: qué aportó cada nodo, el debate pro-fraude vs pro-cliente enfrentado en dos columnas, la decisión del árbitro y las políticas citadas por el RAG.
   2. Evaluación: distribución de decisiones, latencia y costo por nodo, tasa de escalamiento a humano, y los resultados del benchmark de modelos.
   
   Esa vista de debate lado a lado es tu mejor activo de demo; ninguna skill te la va a proponer sola, tienes que pedirla.
6. skills y plugins:
   - Plantear un borrador usando el conector Figma y vamos iterando
   - Hacer uso del skill "frontend-design"
7. Visualización del grafo: React Flow para el panel de detalle del punto 5.1 —
   representar la topología real de LangGraph (nodos y aristas) y, superpuesta,
   la ejecución del caso puntual (qué corrió, qué se degradó). La topología no
   se dibuja a mano: se deriva de `build_graph().get_graph()`, el mismo origen
   que ya usa `scripts/export_graph_diagram.py` para el PNG del README — un
   script hermano exporta esa estructura como JSON para que React Flow la
   consuma, en vez de mantener dos copias de la topología que puedan
   desincronizarse. La ejecución por caso sale de `agent_route` y
   `degraded_agents` de `CaseDetail`, ya en el contrato — sin endpoint nuevo.
   Importante: `agent_route` es una secuencia de supersteps **aplanada**, y la
   adyacencia dentro de un grupo no implica precedencia causal (§2.5 del
   contrato) — dibujar la topología real (con sus ramas paralelas) y sólo
   superponerle el estado de ejecución evita ese error por construcción, en
   vez de dibujar `agent_route` como si fuera una cadena.

## 1. Por qué esta etapa y no CI/despliegue

El reto pide explícitamente *"web App (**Backend + Frontend**)"*. Hasta acá
sólo se construyó el backend: motor de agentes, grafo, y desde la etapa
anterior, la frontera HTTP completa. CI/despliegue necesita algo terminado
para desplegar — el orden natural es cerrar la aplicación primero.

---

## 2. Lo que ya está decidido — el contrato, otra vez

Igual que la etapa anterior, **el contrato ya especifica qué consume cada
vista** (§3, "Dashboard del analista"). No es una decisión de esta etapa,
es la referencia:

| Vista | Consume | Qué muestra |
|---|---|---|
| **Cola** | `GET /cases?status=PENDING_HUMAN` → `Page[CaseSummary]` | lista paginada, filtrable por estado |
| **Detalle** | `GET /cases/{id}` → `CaseDetail` | transacción, contexto del cliente (`null` = *"cliente sin perfil previo"*, no un hueco), señales con severidad, citas internas y externas, debate pro/contra, riesgo + confianza + explicación de auditoría, explicación al cliente, acción (Aprobar/Rechazar + notas → `POST .../resolution`) |
| **Vista de políticas** | `GET /api/v1/policies` → `list[PolicyRead]` | cada política con estado (activa/excluida/pendiente/obsoleta); alta **no disponible** todavía (ADR-0017) |
| ~~Compositor de vinculación~~ | `GET /api/v1/predicates` → `list[PredicateSpec]` | **omitido esta etapa** (§4.3): sin formulario de alta que lo consuma, el endpoint queda listo pero sin UI hasta que exista la Fase 3 del catálogo (ADR-0017) |

**El detalle tiene dos casos que la interfaz tiene que manejar
explícitamente**: `customer: null` (mostrar *"cliente sin perfil previo"*,
que es información de fraude, no un hueco vacío) y `degraded_agents` no
vacío (mostrar qué evidencia faltó al decidir, no ocultarlo).

---

## 3. Dónde está el sistema

| Pieza | Estado |
|---|---|
| Motor de agentes completo: 9 nodos, Threat Intel, Debate, Arbiter con LLM | ✅ |
| Evaluación de calidad (DeepEval, no bloqueante) | ✅ |
| **API FastAPI + HITL**: los cuatro puntos de escritura, sólo lectura de políticas/predicados | ✅ |
| **Dashboard del analista (frontend)** | ⬜ **esta etapa** |
| CI, imagen, despliegue | ⬜ |

`uv run uvicorn multiagent_fraud_detection.api.app:app --reload` levanta la
API real contra la que este frontend va a hablar.

---

## 4. Lo primero que hay que decidir

### 4.1 Stack del frontend — resuelto en §0

**Decidido**: SPA (Vite + React + TypeScript + Tailwind + shadcn/ui) en
`dashboard/`, hermano de raíz con toolchain propio. Dockerfile multi-etapa
(`node:22-alpine` → `npm run build` → `COPY --from` del `dist/`), montado
con `StaticFiles` detrás de las rutas del API, en la misma imagen.

Esto resuelve la disyuntiva que esta sección planteaba —server-rendered
para evitar CORS— por otra vía: **una sola imagen, un solo origen**, así
que el SPA tampoco necesita CORS. El argumento de **no hay autenticación
todavía** (deuda declarada, acta 09 §6.1) sigue vigente, pero ya no decide
el stack.

### 4.2 Notificación de la cola: polling, ya decidido

El contrato ya lo resolvió (§5, decisión 3): **polling en v1**, WebSocket
como mejora futura (entregable 10). No hay que reabrir esto.

### 4.3 Formulario de alta de políticas — omitido esta etapa

**Decidido**: no se construye, ni siquiera deshabilitado. `POST
/api/v1/policies` no existe (ADR-0017: la Fase 3 —tablas, altas
dinámicas— "se decide y ejecuta en una etapa aparte, cuando haya una
necesidad real... no sólo la promesa del contrato"). Un formulario de alta
necesitaría el compositor de condiciones compuestas —predicados +
parámetros tipados por `ParamSpecRead.kind`— para un envío que no puede
llegar a ningún lado: media implementación para un requisito de una fase
que todavía no tiene ni ADR de esquema propio.

`GET /predicates` queda sin consumidor de frontend esta etapa —el endpoint
ya demuestra que el backend está listo; no necesita una UI que lo consuma
para probarlo—. La vista de políticas se limita a la lista de sólo lectura
(`GET /policies`); el compositor se retoma el día que la Fase 3 exista.

### 4.4 Cómo se prueba una interfaz

El proyecto no tiene precedente de testing de UI. Al menos verificar a mano
—capturas o video, que la rúbrica pide (ítem 8)— que las dos vistas
principales funcionan contra la API real, con casos que ejerciten
`customer: null` y un caso con `degraded_agents` no vacío.

### 4.5 Fuente de datos de la vista de Evaluación (§0, punto 5.2)

El punto 5.2 de §0 agrega una vista de Evaluación —distribución de
decisiones, **latencia y costo por nodo**, tasa de escalamiento a humano,
resultados del benchmark de modelos— que **no tiene endpoint en el
contrato** (§2.3) ni respaldo en `Decision`/`CaseDetail`. Entra en el
alcance de esta etapa (confirmado), pero falta decidir de dónde sale cada
dato:

- **Distribución de decisiones** y **tasa de escalamiento**: derivables hoy
  de `GET /cases` (agregación en el cliente, o un endpoint de agregación
  nuevo). No dependen de LangSmith.
- **Latencia y costo por nodo**: no existen en ningún lado todavía.
  LangSmith es la capa declarada para esto desde v0.1 del contrato
  (ADR-0013), pero **nunca se conectó** — ver deuda en §7. Implementar el
  wiring es prerequisito de esta parte de la vista, no un detalle de UI.
- **Benchmark de modelos**: ubicar dónde vive ese resultado hoy (¿DeepEval?
  ¿un script suelto?) antes de asumir que hay algo que servir.

**Decisión pendiente**: ¿esta etapa incluye el wiring de LangSmith (alcance
nuevo, no sólo frontend) o la vista de Evaluación arranca sólo con lo que
ya es servible (distribución + escalamiento), y "latencia/costo por nodo"
queda declarado como *sin datos todavía*?

> La forma de conectar LangSmith, si se hace, ya está resuelta:
> `wrap_anthropic()` sobre los tres clientes, no migrar a `ChatAnthropic`
> (ver §7). Lo que sigue abierto es únicamente el *cuándo*.

---

## 5. Los principios que la etapa no puede romper

1. **El texto que el titular recibe nunca llega al dashboard sin pasar por
   `explanation_customer`.** El dashboard no reconstruye explicaciones —las
   muestra tal cual las sirve `CaseDetail`.
2. **La cita autoriza el veredicto, no lo acompaña** (ADR-0011) — el
   dashboard puede asumir que toda política en `matched_policies` tiene su
   cita en `citations_internal`; no tiene que validar esa garantía, el
   backend ya la hace cumplir.
3. **Polling, no WebSocket** (§4.2 arriba).
4. **`PENDING_HUMAN` es terminal para el grafo** — resolver un caso es una
   llamada HTTP (`POST .../resolution`), nunca "reanudar" nada del lado del
   grafo.

---

## 6. Lo que hay que saber para no repetir errores

- **Un gate no compara con igualdad estricta contra la salida de un
  componente no determinístico** (`08-llm-agents.md` §2) — aplica a
  cualquier verificación automatizada de esta etapa que involucre un
  veredicto real del Arbiter.
- **`app.dependency_overrides` engancha por identidad de función**
  (`09-api-hitl.md` §4) — relevante si el frontend termina viviendo en el
  mismo proceso FastAPI y se le agregan tests.
- **Sin autenticación todavía**: cualquier decisión de UI que asuma
  "sesión del analista" tiene que declarar ese supuesto explícitamente, no
  construir sobre un mecanismo que no existe.

---

## 7. Deuda abierta (heredada, no de esta etapa)

| Deuda | Dónde |
|---|---|
| `fundamentacion_del_debate` con scores bajos, sin diagnóstico | acta 08 §6.3 |
| Golden set en 7 casos, no ~15; sin caso de agente degradado | acta 08 §6.1, §6.2 |
| `SAFE_THEMES` necesita revisión con criterio **legal** | acta 06 §6.5 |
| Sin autenticación en los endpoints HITL | acta 09 §6.1 |
| `POST /api/v1/policies` no existe (Fase 3 del catálogo) | acta 09 §6.2 / ADR-0017 |
| Un restart de proceso a mitad de un caso lo deja atascado en `ANALYZING` | acta 09 §6.3 |
| **LangSmith declarado desde v0.1 y "ya decidido" (ADR-0013) como capa de observabilidad de los entregables 6 y 7, pero nunca conectado**: `settings.py` no lee `LANGSMITH_*`; `narrator.py`, `judge.py` y `searcher.py` usan el SDK crudo de Anthropic. **Resuelto cómo, no cuándo**: envolver los tres clientes con `langsmith.wrappers.wrap_anthropic` — no migrar a `ChatAnthropic`, que exigiría rehacer la salida estructurada nativa de `judge.py` (`messages.parse`) y la herramienta de búsqueda web nativa de `searcher.py` (`web_search_20250305`), ninguna con equivalente maduro en LangChain hoy. La migración a `ChatAnthropic` queda **anotada como exploración futura, con su propio ADR si se retoma** — no es parte de esta etapa | hallazgo 2026-08-13, ver §4.5 |

---

## 8. Después de esta etapa

**CI, imagen y despliegue** — la última fila `⬜` del README. Con el
frontend cerrado, hay una aplicación completa que empaquetar y desplegar.

---

## 9. Comandos de arranque

```bash
docker compose up -d && uv run alembic upgrade head && uv run python scripts/seed.py

uv run pytest                                        # 279, sin red ni base
uv run python scripts/check_policies.py --source=db  # 7000/7000
uv run python scripts/smoke_api.py                   # la API de punta a punta

# La API real, para que el frontend tenga contra qué hablar:
uv run uvicorn multiagent_fraud_detection.api.app:app --reload
```

`GEMINI_API_KEY` y `ANTHROPIC_API_KEY` son opcionales para los gates
determinísticos.

---

## 10. Documentación de referencia

- `contrato_de_interfaz.md` — **v0.10**; **§3** especifica las vistas del dashboard
- `reviews/09-api-hitl.md` — estado completo de la etapa anterior
- `adr/0017` — por qué `POST /api/v1/policies` no existe todavía
