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
| Compositor de vinculación | `GET /api/v1/predicates` → `list[PredicateSpec]` | biblioteca de predicados con sus parámetros, para armar `condition` — sin consumidor real hasta que exista el formulario de alta (bloqueado por ADR-0017, igual que la fila de arriba) |

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

### 4.1 Stack del frontend

El proyecto no tiene precedente: todo el código hasta acá es Python. El reto
no exige un framework específico ("Backend + Frontend", sin más detalle).
Opciones razonables: algo server-rendered simple (Jinja2 servido por la
misma app FastAPI, sin build step, sin CORS que configurar) versus un SPA
separado (React/Vue, consumo por `fetch`, necesita CORS y un origen propio).
Dado que **no hay autenticación todavía** (deuda declarada, acta 09 §6.1) y
el reto valora sobre todo que la app funcione end-to-end y sea demostrable
en video, la opción server-rendered reduce superficie de decisiones nuevas
—sin CORS, sin build pipeline, sin un segundo proceso que orquestar—.

### 4.2 Notificación de la cola: polling, ya decidido

El contrato ya lo resolvió (§5, decisión 3): **polling en v1**, WebSocket
como mejora futura (entregable 10). No hay que reabrir esto.

### 4.3 Qué hace el formulario de alta de políticas si `POST` no existe

`GET /predicates` ya está listo para alimentar un compositor, pero
`POST /api/v1/policies` no existe (ADR-0017). ¿Se construye la UI de alta
igual —deshabilitada, con la razón visible— para demostrar el diseño, o se
omite del todo hasta que la Fase 3 exista? Afecta si esta etapa toca la
Fase 3 del catálogo o la sigue dejando fuera.

### 4.4 Cómo se prueba una interfaz

El proyecto no tiene precedente de testing de UI. Al menos verificar a mano
—capturas o video, que la rúbrica pide (ítem 8)— que las dos vistas
principales funcionan contra la API real, con casos que ejerciten
`customer: null` y un caso con `degraded_agents` no vacío.

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
