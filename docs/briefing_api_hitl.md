# Briefing — próxima etapa: inteligencia externa gobernada

**Sistema Multi-Agente de Detección de Fraude · inicialización de chat**

> Documento corto y **hacia adelante**. El estado completo está en
> [`reviews/06-rag-de-politicas.md`](reviews/06-rag-de-politicas.md); esto es lo
> que la etapa siguiente necesita tener a mano y las decisiones que va a tener
> que tomar.
>
> Contrato vigente: **v0.7** (`contrato_de_interfaz.md`). Sin enmiendas
> acumuladas, sin decisiones conjuntas pendientes.

---

## 1. Por qué esta etapa y no los agentes con LLM

El orden que el proyecto viene usando hace cinco etapas es
**evidencia → citación → decisión → explicación**. Threat Intel es evidencia;
Debate y Arbiter son decisión.

Si los agentes con LLM fueran primero, se construirían **y se medirían** contra un
conjunto de evidencia incompleto: `citations_external` está vacío hoy. Cuando
llegara Threat Intel, los prompts del debate verían material nuevo y **habría que
volver a medir todo** — y la medición es el artefacto caro del entregable 7.

Al revés, Threat Intel se construye sobre un Arbiter que todavía no lo consume y
queda inerte un tiempo. Se difiere la demostración, no el trabajo.

---

## 2. Qué produce Threat Intel y quién lo consume

Corre en el **superstep 0**, en paralelo con Context y Behavioral: es un
**recolector de evidencia**, no un decisor. Produce `citations_external`
—`{url, summary, retrieved_at}`— con el dominio validado contra
`web_search_allowlist`.

| Consumidor | Qué hace con eso | Estado |
|---|---|---|
| Debate Agents | material del argumento pro-fraude | ⬜ stub |
| Arbiter | pesar alerta externa contra historial limpio | ⬜ determinístico |
| `explanation_audit` | *"se detectó alerta externa en el merchant"* | ✅ existe |
| Detalle del dashboard | §3 del contrato | ⬜ |

Es el paso 5 del flujo de ejemplo del reto: *"encuentra alerta reciente de fraude
en ese merchant vía web search gobernada"*, y eso es lo que empuja el caso a
`CHALLENGE`.

---

## 3. Dónde está el sistema

Un caso entra, corre siete supersteps y sale con veredicto, citas verificables,
señales, explicación y **cuatro sellos de auditoría**. Sin LLM en el camino de la
decisión: el veredicto lo produce un árbitro determinístico.

| Pieza | Estado |
|---|---|
| Motor de reglas, catálogo en Postgres, harness 7 000/7 000 | ✅ |
| RAG de políticas: autorización + descubrimiento | ✅ |
| Árbitro **determinístico** (brazo de control, ADR-0006) | ✅ |
| Explicabilidad: auditoría por plantilla, cliente por LLM | ✅ |
| **`web_search_allowlist` + Threat Intel** | ⬜ **esta etapa** |
| Debate Agents · Arbiter con LLM | ⬜ |
| API FastAPI + HITL | ⬜ |
| CI, imagen, despliegue | ⬜ |

Reparto de veredictos: `APPROVE` 90.7% · `ESCALATE_TO_HUMAN` 4.1% ·
`BLOCK` 3.6% · `CHALLENGE` 1.6%.

---

## 4. Lo primero que hay que decidir

### 4.1 Cómo se hace reproducible la evidencia externa

**La decisión que define la etapa.** La web cambia todos los días, y
[ADR-0005](adr/0005-exclusion-de-fp-10-por-evidencia-no-reproducible.md) ya
excluyó FP-10 por exactamente eso:

> Una política cuya evidencia no es reproducible no es evaluable en un harness.

Si el harness sale a buscar en cada corrida, la evidencia externa cae en la misma
categoría. El mecanismo ya está inventado en la etapa anterior
([ADR-0012](adr/0012-el-indice-vectorial-es-dato-derivado-y-versionado.md)):
**buscar una vez, persistir, sellar la versión en la decisión**. El allowlist
gobierna *qué* se puede traer; un caché con sello lo hace *reproducible*.

Sería el **quinto eje de auditoría** —`threat_intel_version` o similar—, con la
misma semántica de nulo que los otros dos: `null` significa *no hubo búsqueda*,
no dato faltante.

### 4.2 La evidencia externa NO puede alimentar `risk_score`

`risk_score` es lo que el harness reproduce 7 000/7 000, y meterle una fuente que
cambia lo rompe. Threat Intel influye en el veredicto **sólo por vía del Arbiter**
— que es justamente por qué queda inerte hasta la etapa siguiente.

Hay que decidirlo de entrada porque condiciona dónde se enchufa el nodo y qué
claves del estado escribe.

### 4.3 La tabla del allowlist

Es la **única tabla del contrato sin modelar**, especificada en §4 desde v0.2:
`domain`, `added_by`, `added_at`, `active`, `reason`.

- Se **siembra** con el seed, como el catálogo.
- Se **cachea en memoria con invalidación**, como `merchant_blacklist` — el
  repositorio con caché TTL ya está extraído y tiene dos consumidores.
- El *enforcement* —rechazar el fetch fuera de la lista y registrar la fuente para
  `citations_external`— es idéntico sin importar dónde viva la lista.

Con ella, `§7.1` pasa de doce tablas a trece y el contrato queda **sin ninguna
tabla pendiente**.

### 4.4 Proveedor de búsqueda

Dos proveedores en uso: **Gemini** para embeddings, **Anthropic** para generación.
Los dos entran por un puerto y se inyectan en `GraphContext`. La búsqueda web es
un tercer puerto —`Searcher`— y hay que elegir proveedor, con el mismo criterio:
cambiarlo debe ser un adaptador y una versión nueva, no una reescritura.

---

## 5. Los cinco principios que la etapa no puede romper

1. **La cita autoriza el veredicto, no lo acompaña.** Vale igual para
   `citations_external`: una URL que no respalda nada es ruido en la traza de
   auditoría ([ADR-0011](adr/0011-citacion-por-identidad-descubrimiento-por-similitud.md)).
2. **Un agente que falla degrada, no aborta.** `@degrades` en los nodos de
   evidencia. Y **`@degrades` solo no alcanza** cuando un nodo tiene dos caminos
   con garantías distintas: el frágil necesita su propio `try`. Threat Intel es
   *todo* camino frágil —red, terceros—, así que su degradación tiene que ser el
   caso normal, no la excepción.
3. **Derivar, nunca escribir.** Lo que se puede calcular no se guarda.
4. **Lo que se audita se sella; lo que se genera no se mide con métricas duras.**
   El carril LLM-as-judge está separado por ADR-0013.
5. **Los gates determinísticos tienen que dar el mismo número dos veces.**
   `check_policies` y `check_retrieval` no pueden depender de la web.

---

## 6. Lo que hay que saber para no repetir errores

- **`asyncio.to_thread` para todo cliente síncrono de proveedor**: bloquea el
  event loop y con él las ramas hermanas del superstep.
- **El texto que se persiste es prosa plana**, sin markdown.
- **Un generador de artefactos versionados tiene que ser determinista entre
  procesos.** `Table.foreign_key_constraints` es un `set`.
- **Una prueba que no puede fallar es peor que no tenerla.** Ocupa el lugar de la
  que serviría y da confianza falsa.
- **Un doble de prueba lleva su propia versión**, para que no pueda confundirse
  con dato real.
- **El modelo/proveedor no es variable de entorno**: sólo la clave. Uno
  configurable por `env` podría cambiarse sin que suba la versión sellada.

---

## 7. Deuda abierta

| Deuda | Dónde |
|---|---|
| `check_retrieval.py` no es gate de CI (necesita índice y caché) | acta 06 §6.4 |
| `SAFE_THEMES` necesita revisión con criterio **legal** | acta 06 §6.5 |
| La costura `GraphContext` ↔ nodos no tiene cobertura de tests | acta 06 §6.3 |
| `logger.exception` produciría 7 000 tracebacks en una caída real | acta 06 §6.5 |
| Exportar `citacion-interna.drawio` a PNG para el README | README |

---

## 8. Después de esta etapa

**Rama de agentes con LLM**: Debate ×2 y Arbiter agéntico, ya con la evidencia
completa. Lo primero a decidir ahí: **qué hace el Arbiter con LLM que el
determinístico no hace** —si sólo lo imita, la comparación del entregable 7 mide
cero—, la cláusula recíproca del invariante (deliberadamente fuera de v0.7), y el
muestreo: cuatro llamadas por caso no corren sobre 7 000 transacciones.

---

## 9. Comandos de arranque

```bash
docker compose up -d && uv run alembic upgrade head && uv run python scripts/seed.py

uv run pytest                                        # 161, sin red ni base
uv run python scripts/check_policies.py --source=db  # 7000/7000
uv run python scripts/smoke_decision.py              # 3 escenarios en DECIDED
```

`GEMINI_API_KEY` y `ANTHROPIC_API_KEY` son opcionales: sin ellas el sistema decide
igual, con el descubrimiento vacío y la explicación por plantilla.

---

## 10. Documentación de referencia

- `contrato_de_interfaz.md` — **v0.7**; **§4** especifica el allowlist
- `reviews/06-rag-de-politicas.md` — estado completo de la etapa anterior
- `adr/0005` — evidencia no reproducible, el precedente que gobierna esta etapa
- `adr/0011` · `adr/0012` · `adr/0013` — citación, índice versionado, qué se mide
- `docs/diagrams/citacion-interna.drawio` — los dos caminos de la citación