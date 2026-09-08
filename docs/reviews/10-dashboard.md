# Repaso — Etapa "Dashboard del analista"
**Sistema Multi-Agente de Detección de Fraude · handoff de continuidad**

> Documento de cierre de etapa. Destila lo decidido y construido en
> `feature/dashboard`, para retomar en el chat siguiente con el contexto ya
> condensado.
>
> Predecesor: `09-api-hitl.md`.
> Decisión de fondo: `adr/0018-*`.

---

## 1. Qué se cerró en esta etapa

El **frontend completo**: dashboard React consumiendo la frontera HTTP que la
etapa anterior dejó lista, más una mejora que el contrato ya anticipaba desde
v0.2 y esta etapa termina de construir — notificación en vivo del progreso del
grafo, por SSE.

| Pieza | Archivo | Verificado |
|---|---|---|
| Scaffold Vite + React + TS + Tailwind v4 + shadcn/ui | `dashboard/` | `tsc`/`lint`/`build` limpios |
| Tipos generados desde el OpenAPI real + topología del grafo | `dashboard/src/api/schema.d.ts`, `data/graph_topology.json` | regenerados contra el backend real |
| Fixtures de desarrollo: 25 casos, todo estado × veredicto relevante | `scripts/seed_dashboard_fixtures.py` | corrida real, idempotente |
| Cola HITL, detalle de caso, catálogo de políticas, evaluación | `routes/{Queue,CaseDetail,Policies,Evaluation}.tsx` | manual, contra Postgres real |
| Empaquetado: Dockerfile multi-stage, SPA servida por FastAPI | `Dockerfile`, `api/app.py` | build real, `docker stop` con shutdown limpio |
| **Bug real**: `customer_snapshot` nunca se persistía en W2 | `graph/nodes.py` | encontrado en una corrida real end-to-end; test de regresión |
| Vitrina pública: 5 casos reales, corridos de punta a punta con LLM real | `scripts/seed_showcase.py` | 5/5, gasto real de Anthropic/Gemini |
| Home: panel fijo (grafo + debate) + escenarios ejecutables en vivo, con cooldown | `routes/Home.tsx`, `data/liveScenarios.ts`, `api/routers/cases.py` | corridas reales repetidas, incl. el 429 |
| "Cómo se construyó": C4 + topología del grafo + ADRs curados | `routes/Architecture.tsx` | manual |
| Sellos de auditoría estructurados, animación de espera honesta | `components/DecisionShowcase.tsx`, `AnalyzingPanel.tsx` | manual |
| **Progreso en vivo por SSE** (ADR-0018): pub-sub en memoria, historial para suscriptores tardíos, estados ran/en-progreso/not-run | `api/case_progress.py`, `api/routers/cases.py`, `hooks/useCaseProgress.ts`, `components/GraphPanel.tsx` | 14 tests + corridas reales con `getComputedStyle` |

---

## 2. El giro: una clase de Tailwind en el DOM no prueba que tenga efecto

Al conectar el streaming real, los nodos del grafo dejaron de iluminarse en
vivo — pero no de una forma obvia: la conexión SSE funcionaba (confirmado con
la pestaña *EventStream* de Chrome y con logs de consola mostrando `ranNodes`
creciendo correctamente evento a evento), y la clase de Tailwind
(`border-primary`, `border-dashed`) sí aparecía en el `className` de cada
nodo. Todo el diagnóstico apuntaba a que el dato llegaba bien. El bug estaba
un nivel más abajo: el propio CSS de React Flow (`.react-flow__node-default`)
fija `border`, `background-color`, `border-radius`, `padding` y `font-size`
con la **misma especificidad** que una única clase de Tailwind —y como esa
hoja se inyecta después—, gana el empate en cascada. La clase queda escrita
en el DOM, pero no hace nada, sin error ni advertencia.

La lección: verificar que un `className` esté presente sólo prueba que React
lo escribió, no que tenga efecto visual. La única prueba real es
`getComputedStyle` sobre el elemento — que fue lo que finalmente lo confirmó,
en ambos sentidos (el bug, y después el arreglo). La corrección definitiva
fue mover el color/tamaño/borde a `style` inline, que por especificidad de
CSS siempre gana frente a cualquier hoja de terceros sin tocar `!important`.

---

## 3. Las decisiones jugosas y su porqué

### 3.1 SSE, no WebSocket literal (ADR-0018)

El contrato (§5, decisión 3) ya anticipaba "WebSocket = mejora" desde v0.2.
El caso de uso es estrictamente unidireccional —el servidor avisa qué nodo
terminó, el cliente nunca contesta nada—, así que un canal bidireccional
sería complejidad sin necesidad. SSE corre sobre HTTP plano y el navegador
reconecta solo vía `EventSource` nativo, sin librería nueva en ningún lado.

### 3.2 El pub-sub es puramente efímero, nunca fuente de verdad

Cambiar `graph.ainvoke()` por `graph.astream(stream_mode="updates")` en W1
es el único cambio de ejecución del grafo; lo que W2 persiste no se toca en
absoluto. El canal de progreso vive en un `dict[UUID, list[Queue]]` a nivel
de módulo, se cierra en el `finally` del wrapper del grafo (éxito o falla), y
`GET /cases/{id}` sigue siendo la única fuente del veredicto.

### 3.3 Historial de eventos para no perder el primer superstep

El primer superstep del grafo (`transaction_context`, `behavioral_pattern`,
`external_threat_intel` — reglas determinísticas, sin LLM) suele terminar en
milisegundos, antes de que el `EventSource` del navegador termine el
handshake. Sin guardar ese historial, esos nodos jamás llegan a mostrarse:
el registro de progreso ahora acumula los nodos publicados por caso, y un
suscriptor —aunque llegue tarde— los recibe en cuanto se conecta.

### 3.4 "En curso" se infiere de la topología, no de un evento que no existe

El stream sólo avisa "este nodo **terminó**", nunca "este nodo **empezó**" —
así que dos nodos que el grafo corre en paralelo de verdad
(`evidence_aggregation` alimenta tanto a `debate_pro_customer` como a
`debate_pro_fraud` en el mismo superstep) se veían como secuenciales en vivo,
porque cada llamada a un LLM tarda lo que tarda. Un tercer estado visual
("en curso", ámbar pulsando) se infiere desde el mapa de predecesores de la
topología: un nodo está en curso si todos sus predecesores ya corrieron pero
él todavía no — sin necesitar un evento de "arranque" que ADR-0018 nunca
prometió.

### 3.5 El cooldown del demo público vive fuera del contrato, a propósito

Un visitante sin autenticación que clickea "ejecutar" repetido gasta LLM
real. El cooldown (`_ultima_corrida_por_escenario`, en memoria del proceso,
sólo mira `transaction_id` con prefijo `LIVE-`) protege ese costo sin tocar
el contrato documentado de `POST /cases` — cualquier llamador real nunca usa
ese prefijo, y nunca lo ve.

---

## 4. Convenciones nuevas fijadas

- **Un color/estado visual que compite con el CSS de una librería de
  terceros va como `style` inline**, nunca sólo como clase de Tailwind — la
  especificidad de una sola clase no gana ningún empate garantizado.
- **El canal de progreso en vivo es efímero por diseño**: nunca reemplaza al
  polling, nunca persiste, se cierra siempre en un `finally`.
- **Un estado visual sin evento propio se infiere de la topología del
  grafo**, no se inventa un evento nuevo que el backend tendría que emitir
  sin necesidad real.

### Footguns verificados en esta etapa

| Trampa | Detalle |
|---|---|
| CSS de React Flow pisa clases de Tailwind | `.react-flow__node-default` fija `border`/`background-color`/`border-radius`/`padding`/`font-size` con la misma especificidad que una clase; al inyectarse después, gana el empate en silencio. Sección 2. |
| `Stop-Process -Force` no mata hijos en Windows | Un `uvicorn --reload` reiniciado a mano deja workers `multiprocessing` huérfanos vivos tras matar sólo el proceso padre — cualquiera de ellos puede seguir respondiendo el puerto sin que `netstat`/`Get-Process` lo delate a tiempo (caché de la tabla de conexiones). El único chequeo confiable es un intento de `bind()` real. |
| `EventSource` sin historial pierde el primer superstep | Nodos determinísticos que terminan en milisegundos, antes de que el navegador conecte, se pierden para siempre si el pub-sub no guarda lo publicado antes de que exista un suscriptor. |
| React StrictMode duplica el logging de un `setState` funcional | `setState((prev) => {...; console.log(...); return next})` se invoca dos veces en desarrollo — React verifica que el actualizador sea puro. No es un bug si un log aparece dos veces; sí lo sería si el efecto no fuera idempotente. |
| `className` en el DOM no prueba efecto visual | Sólo `getComputedStyle` confirma que una regla realmente ganó la cascada. |

---

## 5. Verificación de la etapa

| Gate | Resultado |
|---|---|
| `pytest` | 303 verdes, sin red y sin base (279 al cierre de la etapa anterior) |
| `check_policies.py --source=db` | 7 000/7 000, sin cambios — `domain/engine.py` no se tocó |
| `alembic check` | sin operaciones nuevas — esta etapa no tocó el modelo de datos |
| `export_data_model_diagram.py --check` | al día, 14 tablas (sin cambios) |
| `tsc --noEmit` / `oxlint` / `vite build` (dashboard) | limpios |
| Corrida real contra backend + frontend reales | streaming SSE confirmado nodo por nodo (timestamps reales, 15ms–20s), multi-pestaña (dos suscriptores, misma secuencia), conexión tardía (`done` inmediato), colores verificados con `getComputedStyle`, veredicto final idéntico al que ya daba el polling |

---

## 6. Hallazgos y deuda

### 6.1 Sin autenticación en los endpoints públicos del demo

Mismo criterio que los endpoints HITL (acta 09 §6.1): la rúbrica no la
exige, y el cooldown en memoria ya cubre el riesgo real (gasto de API), no
abuso dirigido a una persona.

### 6.2 Migración a `ChatAnthropic` sigue pendiente, ahora con una razón más concreta

Ya estaba anotada como mejora futura desde la etapa de LangSmith. Esta etapa
suma una segunda: el usuario propuso streaming de tokens del debate en vivo
(timeline tipo chat, con avatares por agente) — inviable de forma limpia con
el SDK crudo de Anthropic (`asyncio.to_thread` sobre una llamada completa),
porque `astream_events` de LangGraph sólo reenvía deltas de token
automáticamente si los nodos usan la interfaz de chat de LangChain. Etapa
propia, con su ADR — anotada, no empezada.

### 6.3 El pub-sub de progreso es por proceso, no por réplica

Con N réplicas, cada una sólo ve el progreso de los casos que ella misma
corre. Aceptado a propósito (ADR-0018): es un agregado visual, no un dato
que el sistema tenga que reconciliar entre instancias.

### 6.4 El cooldown de la demo se resetea con cada restart del proceso

En memoria, sin persistencia — un reinicio del backend (deploy, crash)
limpia todos los cooldowns activos. Aceptado: es protección de costo, no
garantía de seguridad.

---

## 7. Mapa de archivos al cierre

```
dashboard/
├── src/
│   ├── api/{client.ts,schema.d.ts}       # openapi-fetch + tipos generados
│   ├── components/
│   │   ├── GraphPanel.tsx                # estados ran/en-progreso/not-run/synthetic, estilo inline
│   │   ├── AnalyzingPanel.tsx            # panel en vivo; barrido indeterminado como fallback
│   │   └── DecisionShowcase.tsx          # debate, señales, citas, sellos de auditoría
│   ├── hooks/useCaseProgress.ts          # EventSource nativo, sin librería nueva
│   ├── data/{liveScenarios.ts,showcase_cases.json,graph_topology.json}
│   └── routes/{Home,Queue,CaseDetail,Policies,Evaluation,Architecture}.tsx
└── Dockerfile                             # multi-stage, SPA servida por FastAPI

src/multiagent_fraud_detection/api/
├── case_progress.py                       # pub-sub + historial en memoria — nuevo
├── routers/cases.py                       # astream en vez de ainvoke, ruta /stream, cooldown demo
└── app.py                                 # StaticFiles + catch-all SPA (condicional a dist/)

src/multiagent_fraud_detection/graph/nodes.py  # fix: customer_snapshot ahora sí se persiste en W2

scripts/
├── seed_dashboard_fixtures.py             # 25 casos, dev
└── seed_showcase.py                       # 5 casos reales, vitrina pública

tests/
├── test_node_persist.py                   # regresión del fix de customer_snapshot
├── test_case_progress.py                  # pub-sub, historial, endpoint SSE
└── test_api_cases.py                      # cooldown del demo, astream en vez de ainvoke
```

---

## 8. Qué sigue

**Rediseño del dashboard** (plan ya escrito, pendiente de ejecutar): página
"Transactions" con tabla unificada (5 casos reales re-ejecutables + 3
escenarios actuales + 6 diversos elegidos desde `ground_truth.csv`
determinístico, sin gastar LLM en la selección), "Explicación de auditoría"
reestructurada en campos en vez de un párrafo, sidebar + modo oscuro, grafo
sin zoom/pan.

**Deuda declarada para el informe**: sin autenticación (§6.1), migración a
`ChatAnthropic` para viabilizar streaming de tokens del debate (§6.2),
pub-sub por proceso no por réplica (§6.3), cooldown en memoria (§6.4) — las
cuatro explícitas, ninguna es un olvido.

---

## 9. Documentación asociada

- [ADR-0018](../adr/0018-el-progreso-en-vivo-se-transmite-por-sse.md)
- `enmiendas_pendientes.md` — vacío tras publicar; una enmienda hacia v0.11, en `CHANGELOG.md`
- `09-api-hitl.md` — etapa anterior
- `docs/temp/dashboard_mejoras.md` — notas del usuario para la etapa siguiente (gitignored, no versionado)
