# Repaso — Etapa "Agentes determinísticos"
**Sistema Multi-Agente de Detección de Fraude · handoff de continuidad**

> Documento de cierre de etapa. Destila lo decidido y construido en
> `feature/deterministic-agents`, para retomar en el chat dedicado al **RAG de
> políticas internas** con el contexto ya condensado.
>
> Predecesor: `04-dataset-y-seed.md`. Decisión de fondo: `adr/0007-*`.

---

## 1. Qué se cerró en esta etapa

La **capa de reglas completa** y los tres agentes que la usan. Con eso, el motor
determinístico reproduce el ground truth fila por fila, sin base y sin LLM.

| Pieza | Archivo | Verificado |
|---|---|---|
| Parámetros compartidos | `domain/params.py` | CSV byte a byte idéntico |
| Catorce predicados puros | `domain/predicates.py` | 26 tests unitarios |
| Catálogo + validaciones + huellas | `domain/catalog.py` | 20 tests |
| Intérprete | `domain/engine.py` | 12 tests |
| Scoring determinístico | `domain/scoring.py` | 13 tests de propiedad |
| Transaction Context | `graph/nodes.py` | 9 tests |
| Behavioral Pattern | `graph/nodes.py` | 12 tests |
| Evidence Aggregation | `graph/nodes.py` | 11 tests |
| Gate contra ground truth | `scripts/check_policies.py` | **7 000 / 7 000** |
| Smoke contra Postgres | `scripts/smoke_agents.py` | **7 000 / 7 000** |

**Suite**: 111 tests en ~2 s, sin Postgres ni red.

---

## 2. El giro: las políticas no son código

La etapa arrancó con un plan que se cayó a los dos días, y la corrección vino de
una pregunta simple: *¿qué pasa cuando el banco publica una política nueva?*

El plan original traducía las once políticas a funciones de Python. Eso significa
que **cada umbral ajustado es un commit, un build y un despliegue** — y quien
escribe una política de fraude no es un ingeniero, es un oficial de cumplimiento
que reacciona a un patrón que apareció el martes.

La primera corrección tampoco sirvió: metía `condition` y `action` dentro del
JSON del banco. Eso obliga al personal de banca a conocer un vocabulario de
predicados que no es suyo, y escribe campos nuestros en un artefacto ajeno.

Lo que quedó ([ADR-0007](../adr/0007-la-forma-ejecutable-de-una-politica-es-una-vinculacion.md)):

| Artefacto | Dueño | Qué es |
|---|---|---|
| Documento normativo | el banco | prosa con autoridad, la indexa el RAG |
| **Vinculación** | nosotros | la traducción ejecutable, firmada y fechada |
| Biblioteca de predicados | código | catorce operaciones cerradas |

La vinculación guarda una **huella del texto** que tradujo. Si el banco edita
"3x" por "4x", la huella deja de coincidir y la política pasa a `stale`: sigue
citable, deja de evaluarse. El sistema **no puede aplicar un umbral distinto del
que cita**, y eso ahora es estructural, no una convención.

> **La lección transversal: antes de agregar un campo, preguntar de quién es el
> archivo.**

---

## 3. Las decisiones jugosas y su porqué

### 3.1 Los predicados reciben un contexto, no argumentos sueltos

`requires` tiene que existir **como dato** de todos modos: de ahí salen el
despacho (*sin perfil, solo lo que no necesita perfil*), el reparto
Context/Behavioral y la validación estructural. Con argumentos explícitos ese
dato existiría dos veces —en la firma y en el registro— y nada los amarraría.

La contracara: un predicado podría leer `ctx.profile` sin declararlo. Pero la
promesa se verifica sola —revienta en las 96 transacciones sin perfil y el gate
lo atrapa—.

### 3.2 Los predicados devuelven evidencia, no un booleano

`Signal.description` es un campo del contrato que un analista lee en la cola.
*"Monto 1926.61 PEN supera 1241.40 (3× el promedio habitual de 413.80)"* dice
algo; *"monto fuera de rango"* no.

Con `bool`, para mostrar esos números el intérprete tendría que **recalcular el
umbral**, o sea escribir la lógica del predicado por segunda vez fuera del
predicado. Y `observed` le da al Arbiter números en vez de códigos.

### 3.3 El intérprete no corta en el primer predicado que falla

4× el promedio a las 14:00: FP-01 no matchea, pero **el monto sí está fuera de
rango**. Esa observación es cierta y se persiste.

Cortar la perdería, y es justo la clase de señal que más importa: las que no
vienen acompañadas de una política que las explique son las que el Arbiter tiene
que ponderar.

De ahí las dos salidas separadas: las señales siempre; `matched_policies` solo
cuando la conjunción se cumple.

### 3.4 Señales que solo significan algo acompañadas

`AMOUNT_OVER_ABSOLUTE` disparaba en **6 321 de 7 000** transacciones: el umbral
de FP-07 son 135 USD y casi cualquier monto lo supera. Una señal con 90% de tasa
base no es evidencia, es ruido que inunda la tabla que el entregable 6 vigila.

Se resolvió con `standalone=False` en el predicado: se emite solo si su política
matcheó completa. Bajó a 80, que son exactamente los matches de FP-07.

Es el único de los catorce. La distinción existe porque *"monto sobre 135 USD"*
no dice nada; *"sobre 135 USD **en un comercio de la lista negra**"* sí.

### 3.5 Dos números, no uno

El contrato ya lo pedía; acá se eligió la forma **midiendo** sobre las 7 000:

| Fórmula | AUC | mediana BLOCK | APPROVE > 0.5 |
|---|---|---|---|
| **noisy-OR** | **0.994** | 0.625 | 15 |
| suma / 1.5 | 0.989 | 0.500 | 0 |
| max + conteo | 0.993 | 1.000 | 202 |

`max + conteo` satura —BLOCK y ESCALATE indistinguibles— y la suma comprime.
noisy-OR además es **conmutativo**, que no es opcional: las señales llegan de dos
agentes paralelos y su orden de arribo es arbitrario.

`base_confidence` es la U: `0.5 + |risk − 0.5|`, menos `0.15` por agente caído,
`0.10` por contradicción y `0.10` por falta de perfil, con piso en `0.05`.

### 3.6 La ausencia de evidencia no es evidencia

`NO_CUSTOMER_PROFILE` **no entra en el `risk_score`**. Es la única señal que no
sale de un predicado: no describe la transacción, describe que faltó con qué
compararla.

Sumarla al riesgo es el mismo error de categoría que sumar un agente caído, y
castigaría a las 96 transacciones sin perfil por algo que no es de ellas. Pesa en
la confianza, y una sola vez.

Lo destapó un test que escribí esperando lo contrario.

### 3.7 El reparto Context / Behavioral no se eligió: se derivó

Sale de los insumos que declara cada predicado, y coincide exactamente con la
rama `if perfil is None` del etiquetador. Resultado **1 contra 9**.

Context no es un agente anémico: es el **piso de evidencia**, el único que sigue
produciendo señales cuando el cliente no existe —el escenario que el contrato
llama *"el que más importa"*—.

Ninguna política cruza los dos nodos, y eso se volvió **validación estructural**:
una que lo hiciera falla al cargar.

---

## 4. Convenciones nuevas fijadas

- **"Agentes de lógica pura" se abandona.** Dos de los tres hacen I/O. Lo puro es
  la capa de abajo. Vocabulario: `domain/` son **reglas puras**; los nodos son
  **agentes determinísticos**.
- **El término "agente" se sostiene en su acepción clásica**: los tres son
  agentes reflexivos, y Behavioral es *model-based* —su modelo del mundo es el
  perfil—. Va argumentado en el informe.
- **Acumulador ≠ consolidado.** `signals` y `matched_policies` acumulan con
  reducer aditivo y **no se pueden reemplazar**; Evidence Aggregation deja la
  versión consolidada en `evidence` y `policies`, con última escritura.
- **Aggregation va sin `@degrades`**: si falla no hay nada que consolidar, y
  degradar produciría un caso sin scores que el invariante rechazaría mucho
  después, lejos de la causa.
- **Duplicar la lógica, compartir las constantes.** El etiquetador y el
  intérprete son implementaciones independientes a propósito; comparten FX,
  promedios por segmento y precedencia, porque un desacuerdo sobre el factor del
  sol no es un hallazgo, es ruido.
- **Los promedios por segmento se congelan**, no se consultan: derivarlos de la
  población movería el umbral al agregar un perfil.

### Footguns documentados

| Trampa | Detalle |
|---|---|
| `@wraps` y firmas | El wrapper de `@degrades` debe aceptar `*args`: LangGraph inspecciona la firma **original** y pasa `runtime` |
| Historial y doble conteo | El repositorio filtra con `<=`, los predicados hacen `len(previas) + 1`. Sin `exclude_transaction_id` la transacción se cuenta dos veces |
| `monotonic()` en Windows | Resolución de ~15 ms: `elapsed > 0` puede ser falso. Un TTL de 0 no vencía. **Verde en CI, rojo en local** |
| Reducer aditivo | Devolver una lista consolidada la **concatena**. No se puede reemplazar sin otra clave |
| `pytest-asyncio` | Sin él, los tests `async` se **saltean en silencio** |

---

## 5. Verificación de la etapa

Cuatro capas, cada una atrapando lo que la anterior no puede:

1. **111 tests unitarios** (~2 s, sin base): bordes que el dataset no cubre —cruce
   de medianoche, listas vacías, cambio de perfil posterior al cargo— y las ocho
   validaciones del catálogo, que son lo que reemplaza al compilador.
2. **`check_policies.py`** (~1 s): el catálogo sobre las 7 000 contra el ground
   truth. **0 discrepancias en políticas y en decisiones**, F1 = 1.000 en las
   diez. Probado que muerde: cambiar `factor: 3` por `4` produce 20 divergencias
   y código de salida 1.
3. **`smoke_agents.py --todas`**: lo mismo, pero con el historial saliendo de
   Postgres, donde el futuro **sí está en la tabla**. **7 000 / 7 000**, y 96
   clientes sin perfil detectados —el número exacto del dataset—.
4. **`smoke_graph.py`**: el grafo completo escribiendo a la base. Verifica el
   orden determinístico, la separación acumulador/consolidado, y que
   `matched_policies` y `policy_catalog_version` se sellen.

> La capa 3 existe porque la 2 arma el historial en memoria, donde el invariante
> *as-of* se cumple por construcción. Un `now()` en lugar del timestamp de la
> transacción **funciona bien en producción** —el futuro no existe cuando llega
> el caso— y solo miente en evaluación, hacia arriba.

---

## 6. Estado del catálogo

```
catálogo 2025.1-b1 · {'active': 10, 'excluded': 1, 'pending': 0, 'stale': 0}

Context evalúa   : FP-07
Behavioral evalúa: FP-01 02 03 04 05 06 08 09 11
Excluida         : FP-10 (ADR-0005, evidencia no reproducible)
```

Distribución de señales sobre las 7 000, ninguna dominando:

```
NEW_DEVICE 640 · AMOUNT_OVER_USUAL_AVG 524 · FOREIGN_COUNTRY 503
NEW_ACCOUNT 445 · AMOUNT_OVER_SEGMENT_AVG 212 · OUTSIDE_USUAL_HOURS 175
NEW_CHANNEL 127 · MERCHANT_BLACKLISTED 81 · AMOUNT_OVER_ABSOLUTE 80
IMPOSSIBLE_TRAVEL 71 · RECENT_PROFILE_CHANGE 69 · DAILY_LIMIT_EXCEEDED 66
MICRO_CHARGE_SEQUENCE 60 · DEVICE_VELOCITY 59
```

---

## 7. Discrepancias conocidas y deuda

**FP-03 tiene dos ejes.** El repositorio consulta por dispositivo cruzando
cuentas; el etiquetador filtra por cliente **y** dispositivo. Medido: 1 337
dispositivos, 27 compartidos, 77 transacciones, **cero divergencia**. Se declaró
`axis=device` y se documentó.

**Sin perfil, el motor evalúa más políticas que el etiquetador.** FP-03 y FP-05
no dependen del perfil, pero el etiquetador hace `continue` tras FP-07. Cero
casos hoy. Hay un test que lo deja escrito en algo que se ejecuta.

**`observed` no viaja al estado.** `WorkingSignal` hereda de `SignalRead` y ese
campo no existe en el contrato. Sobrevive dentro de `description`. El Arbiter
recibiría texto donde podría recibir números; se decide con el prompt delante.

**Sin *shadow mode*.** Una vinculación nueva no tiene ground truth: el validador
atrapa errores de forma, no de semántica. Activar una política sin correrla
contra tráfico histórico convierte la agilidad en una forma rápida de bloquear
clientes legítimos. Va al entregable 10.

---

## 8. Mapa de archivos al cierre

```
├── data/policies/
│   ├── fraud_policies_2025.1.json     # del banco, NO se toca
│   └── policy_bindings_2025.1.json    # las once vinculaciones, firmadas
├── docs/
│   ├── catalogo_de_politicas.md       # spec de la capa de reglas
│   └── adr/0007-la-forma-ejecutable-...md
├── scripts/
│   ├── _dataset.py                    # adaptador CSV → dominio (sin db/)
│   ├── check_policies.py              # gate offline
│   └── smoke_agents.py                # gate contra Postgres
├── src/multiagent_fraud_detection/
│   ├── domain/
│   │   ├── params.py                  # FX, promedios congelados, precedencia
│   │   ├── predicates.py              # los catorce
│   │   ├── catalog.py                 # loader + 8 validaciones + huellas
│   │   ├── engine.py                  # intérprete
│   │   └── scoring.py                 # risk_score + base_confidence
│   └── db/repositories/
│       ├── customer_behavior.py       # perfil → schema, no ORM
│       └── merchant_blacklist.py      # + caché con TTL
└── tests/                             # 111 tests, ~2 s
```

---

## 9. Qué sigue: el RAG de políticas internas

Es el consumidor natural de lo que quedó armado, y la **fase 3 de ADR-0007** entra
con él.

1. **Las dos tablas de gobernanza**: `fraud_policies` (documentos, del banco) y
   `policy_bindings` (traducciones, nuestras), con ciclos de vida
   independientes. El catálogo deja de leerse de archivos.
2. **Chunk + embed** de los documentos en pgvector, que está habilitado desde la
   primera migración y todavía no se usó.
3. **`citations_internal`**, que es lo que hoy bloquea todo veredicto autónomo:
   sin RAG el invariante manda cada caso a `ESCALATE_TO_HUMAN`, y por eso el F1
   de la **decisión del sistema** todavía no es medible. Lo que sí se mide es
   `expected_policies`.
4. **La query se arma desde las señales**, no desde el `policy_id`: por eso el
   nodo corre después de la ola 1. Puede recuperar una política que el motor no
   disparó, y esa discrepancia es evidencia para el Arbiter.
5. **FP-10** aparece acá: tiene documento y no tiene vinculación. El RAG la cita;
   el motor no la evalúa.

Preguntas abiertas para esa conversación:

- ¿El chunking es por política o por párrafo? Con once líneas la pregunta es
  artificial; con circulares reales no.
- ¿Qué modelo de embeddings, y cómo se versiona el índice cuando cambie?
- ¿Cómo se mide la recuperación, si el ground truth habla de políticas
  disparadas y no de políticas recuperadas?
- ¿El Arbiter ve `matched_policies` y `citations_internal` por separado, o
  consolidados?

---

## 10. Documentación asociada

- `catalogo_de_politicas.md` — la capa de reglas: documento, vinculación, predicados.
- `adr/0007-la-forma-ejecutable-de-una-politica-es-una-vinculacion.md`
- `adr/0006-reparto-deterministico-y-llm.md` — qué motor usa cada nodo.
- `04-dataset-y-seed.md` — etapa anterior.
- `contrato_de_interfaz.md` — v0.6 incorpora las enmiendas de esta etapa.
