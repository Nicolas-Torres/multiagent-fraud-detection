# Repaso — Etapa "Dataset y seed"
**Sistema Multi-Agente de Detección de Fraude · handoff de continuidad**

> Documento de cierre de etapa. Destila lo decidido y construido en
> `feature/dataset-seed`, para retomar en el chat dedicado a los **agentes de
> lógica pura** con el contexto ya condensado.
>
> Predecesor: [`03-grafo-y-persistencia.md`](03-grafo-y-persistencia.md).
> Contrato vigente: `contrato_de_interfaz.md` **v0.5**.

---

## 1. Qué se cerró en esta etapa

El dataset dejó de ser un insumo y pasó a ser un **instrumento de medición**, y la
base dejó de estar vacía.

| Entregable | Estado |
|---|---|
| Generador de dataset con confusores y casos límite | ✅ |
| Ground truth de 7 000 etiquetas | ✅ |
| Validador del dataset (gate de CI) | ✅ |
| Siete campos de evaluación en `customer_behaviors` | ✅ |
| Índices de historial + repositorio *as-of* | ✅ |
| Tabla `merchant_blacklist` | ✅ |
| Script de seed idempotente | ✅ |
| Smoke test del seed (18 comprobaciones) | ✅ |
| Contrato v0.5 · ADR-0003, 0004, 0005 | ✅ |

**Cadena de migraciones** desde el cierre de la etapa anterior:

```
694142a4c8b6  (agent_errors)
 → 073738cbc0ec  (campos de evaluación en customer_behaviors)
   → 699755dfc00e  (índices de historial)
     → 1276e208c3d9  (merchant_blacklist)  ← head
```

**Pendiente de modelar**: `web_search_allowlist` (§4 del contrato). Se decidió
que entra **con su consumidor**, no acá: sus filas son dominios web sin relación
con el dataset, y sembrarla ahora crearía una tabla que nadie lee.

---

## 2. La premisa que cayó a mitad de camino

El equipo de banca se retiró del curso. El briefing de la etapa dedicaba una
sección entera a ocho peticiones que había que mandarles y esperar.

Al desaparecer el interlocutor, esos ocho puntos dejaron de ser bloqueos y se
volvieron **ediciones a un archivo nuestro**. El cambio no fue de esfuerzo sino
de categoría: el dataset pasó de dato recibido a artefacto diseñado, que es
exactamente lo que el entregable 2 pide documentar.

Lección transversal: *cuando desaparece la dependencia externa, revisar qué
decisiones se habían tomado suponiéndola*. La exclusión de una política y la
redefinición de otra se revirtieron al recalcular con la premisa nueva.

---

## 3. Las decisiones jugosas y su porqué

### 3.1 Un dataset sin falsos positivos posibles no mide nada

El hallazgo que reorientó la etapa. Medido sobre el dataset original:

| Señal | Activaban | Legítimas |
|---|---|---|
| país ≠ habitual | 186 | **0** |
| dispositivo ≠ habitual | 211 | **0** |
| canal ≠ habitual | 61 | **0** |

`país ≠ habitual → fraude` tenía **precisión 1.0**. No porque fuera buena regla,
sino porque el dataset hacía **imposible el falso positivo**: la clase que la
precisión mide no existía.

Etiquetar no lo arreglaba. Las etiquetas dan recall; lo que faltaba era población
negativa difícil. Ocho confusores después, el mismo `if` tiene precisión 16%.

Detalle: los confusores se **tallan del relleno**, no se suman encima. El total
sigue siendo 7 000 y la tasa base no se mueve.

Registrado en [ADR-0003](../adr/0003-dataset-sintetico-como-instrumento-de-evaluacion.md).

### 3.2 Etiquetar por la regla, no por la intención

El generador sabe qué rama sorteó. Esa información **se descarta**.

Con confusores presentes, un patrón "normal" puede satisfacer una política por
accidente. Al implementarlo se comprobó: **14 transacciones satisfacen dos
políticas a la vez** (`FP-02;FP-05` es la más común). Etiquetadas por rama,
quedarían marcadas `APPROVE` siendo positivos reales, y el harness castigaría al
sistema por acertar.

> La verdad de una etiqueta la fija la regla aplicada al resultado, no la
> intención de quien generó el dato.

### 3.3 El invariante *as-of*

`transactions` es a la vez fuente de casos e historial. Como el seed carga todo de
una vez, una consulta sin acotar devuelve transacciones que **en el instante
analizado no existían**.

Lo insidioso es la asimetría: en producción es imposible de violar —el futuro no
está en la tabla—, así que un agente sin filtro **funciona bien allá y solo falla
en evaluación**. Y falla hacia arriba, inflando su propio recall.

Se hace cumplir en un único módulo, `db/repositories/transaction_history.py`.

> Un invariante que depende de que cada autor lo recuerde no es un invariante.

Registrado en [ADR-0004](../adr/0004-consultas-de-historial-as-of.md).

### 3.4 Dos ejes de acceso, no uno

La primera propuesta fue "una sola consulta de ventana por cliente, las políticas
filtran en memoria". Estaba mal: **FP-03 filtra por dispositivo, no por cliente**,
porque un dispositivo usado con varias cuentas es exactamente la señal que busca.

De ahí que sean dos funciones y dos índices compuestos. El error se atrapó al
escribir la consulta, no al diseñarla — que es el argumento del briefing para
decidir los índices "con la consulta escrita, no antes".

### 3.5 `usual_channel` es singular por cardinalidad, no por gusto

`Channel` tiene dos valores. Una lista tendría un elemento —idéntico al
singular— o los dos, y entonces FP-06 ("canal nuevo con monto alto") **nunca
puede dispararse**: la política muere. Una lista de 2 sobre 2 posibles es una
tautología.

Disparador de revisión documentado: el día que `Channel` crezca (ATM, POS, API).

### 3.6 Upsert, no `DO NOTHING`

`ON CONFLICT DO NOTHING` parece la opción prudente y es la peor: si el dataset se
regenera y el seed vuelve a correr, no pasa nada, la base conserva las filas
viejas y uno cree que recargó. **Fallo silencioso justo en el dato que sostiene
todas las métricas.**

`DO UPDATE` es la versión por fila del principio que ya regía el nodo persistidor:
*un reintento sustituye, no acumula*.

`--reset` (`TRUNCATE ... CASCADE`) existe para cuando el dataset nuevo tenga menos
filas que el viejo —el upsert no borra huérfanas—, pero arrastra `cases` por el
FK y por eso es explícito.

### 3.7 La moneda es de la cuenta, no del país

77 de 999 clientes tenían historial en dos monedas. Comparar "3× el promedio"
entre ellas fabrica falsos positivos.

No es una simplificación: una tarjeta liquida en la moneda de su cuenta. La
dimensión internacional sobrevive intacta porque `country` sigue variando.

Corolario que casi se pasa por alto: **el factor de escala se aplica también a
`daily_limit` y a los umbrales monetarios de las políticas**. Un "cobro de
centavos" de 0.50 literal son 0.000125 USD en pesos colombianos, y FP-04 dejaba
de tener sentido.

### 3.8 `segment` es enum porque el sistema agrupa por él

El criterio para enum no es cuántos valores tiene, sino **si el valor lo produce
el dominio o lo transporta el dato**. FP-08 compara contra el promedio del
segmento, o sea que la aplicación agrupa por esa columna. Un `varchar` admitiría
`Retail` y `retail` como grupos distintos y partiría el promedio sin que nada
falle.

Por el mismo criterio, `currency` y `timezone` **no** son enums: son códigos de
estándares externos que crecen sin que nosotros decidamos.

### 3.9 Primera tabla de gobernanza

`merchant_blacklist` estrena la categoría que §4 del contrato definió para el
allowlist: dato mutable, administrado por un humano, con audit trail.

PK natural con bandera `active`, no surrogate con historial. La historia no se
pierde porque **el caso congela su propia evidencia** en `signals`: si el comercio
se retira en marzo, el caso de enero sigue diciendo qué decidió y por qué. Mismo
principio que `cases.customer_snapshot`.

Excepción de nombre documentada: singular, contra la convención plural de las
otras siete tablas, por consistencia con su hermana `web_search_allowlist`.

---

## 4. Convenciones nuevas fijadas

- **El adaptador traduce forma; nunca adivina semántica.** Un defecto de forma se
  queda en la fuente y se traduce (el typo `chanel`, las listas con `;`): o el
  mapeo existe o revienta ruidosamente. Una ambigüedad semántica se corrige en la
  fuente, porque adivinarla es el bug de `America/Lima` en miniatura.
- **Rangos, no números exactos, en las verificaciones de datos generados.** Los
  casos límite se sortean con probabilidades; un `== 50` hace perseguir falsos
  fallos.
- **Una celda vacía es una lista vacía, no un dato faltante.** `[""]` haría que
  "sin dispositivo habitual" pareciera un dispositivo llamado cadena vacía.
- **`server_default` para literales SQL va envuelto en `sa.text()`**, en la
  migración **y** en el modelo. Autogenerate emite string plano, que Postgres
  renderiza entrecomillado (`DEFAULT 'true'`).
- **Un test no es dueño de la base**: limpia al entrar *y* al salir.
- **Los umbrales monetarios de las políticas se expresan en una moneda de
  referencia** y se convierten, nunca literales.

### Footguns documentados

| Trampa | Detalle |
|---|---|
| `keep_default_na=False` | Sin él, pandas convierte celdas vacías en `NaN` y las comparaciones con `""` fallan en silencio |
| `itertuples` y guiones bajos | Renombra las columnas que empiezan con `_`; una columna auxiliar `_ts` se vuelve inaccesible |
| Límite de parámetros de psycopg | 65 535. 7 000 filas × 9 columnas = 63 000: pasa hoy, revienta al agregar una columna |
| `np.random.seed` | Usa el `RandomState` legado, cuyo stream numpy congeló. Reproducible **entre versiones** |
| Seed perdido en una reescritura | El docstring lo mencionaba, el código no lo tenía. Solo apareció comparando dos corridas byte a byte |

---

## 5. Verificación de la etapa

**`scripts/validate_dataset.py`** — verifica los tres CSV sin tocar la base.
Devuelve código ≠ 0, lo que lo vuelve gate de CI sin modificarlo. Comprueba
casos límite, zonas IANA resolubles, la fracción benigna de cada dimensión y que
`FP-10` no aparezca en las etiquetas.

**`scripts/smoke_seed.py`** — 18 comprobaciones sobre lo que quedó en Postgres,
releyendo en sesión nueva. Seis bloques: conteos, normalización del adaptador,
casos límite, coherencia de moneda, invariante *as-of* y frontera `Read`.

El bloque *as-of* es el más valioso: **es la única comprobación del archivo que no
se puede hacer en producción**, porque allá la violación es imposible y por tanto
invisible.

**Reproducibilidad**: los tres CSV salen idénticos byte a byte entre corridas y
entre versiones distintas de numpy y pandas. `git diff --exit-code data/` después
de regenerar es una guarda válida.

**Índices**, sobre la base sembrada:

| | Index Scan | Seq Scan forzado |
|---|---|---|
| Buffers | 4 | 81 |
| Ejecución | 0.373 ms | 5.423 ms |
| Filas descartadas | 0 | 6 995 |
| Nodo `Sort` | innecesario | 25 kB |

El compuesto sirve dos veces: cubre el filtro **y** el orden, así que el
`ORDER BY timestamp` sale gratis. Predije que con 7 000 filas ganaría el
`Seq Scan` y me equivoqué: lo que manda es la **selectividad** (0.1%), no el
volumen absoluto.

---

## 6. Estado del dataset

| Archivo | Filas |
|---|---|
| `customer_behaviors.csv` | 1 000 |
| `transactions.csv` | 7 000 |
| `ground_truth.csv` | 7 000 |
| `policies/fraud_policies_2025.1.json` | 11 |

**Positivos por política** — las diez del alcance superan los 55, que es el piso
para que un F1 signifique algo:

| | | | |
|---|---|---|---|
| FP-01 | 61 | FP-06 | 57 |
| FP-02 | 79 | FP-07 | 80 |
| FP-03 | 59 | FP-08 | 66 |
| FP-04 | 59 | FP-09 | 69 |
| FP-05 | 71 | FP-11 | 66 |

`APPROVE` 6 347 · `ESCALATE_TO_HUMAN` 286 · `BLOCK` 252 · `CHALLENGE` 115.

**Casos límite** que antes estaban en cero: 49 clientes nocturnos, 27 sin
dispositivo habitual, 29 sin país habitual, 23 multi-país, 96 transacciones de
clientes sin perfil.

Esquema y semántica completos en [`data/README.md`](../../data/README.md).

---

## 7. Dos correcciones de fondo

**La numeración de políticas estaba corrida.** El análisis previo leyó los
comentarios del generador en vez del catálogo, y a partir de la octava se
desplazaban un número: de ahí salió un "falta FP-08" y un FP-12 inexistente. El
catálogo real es `FP-01`…`FP-11` sin huecos.

Consecuencia: la política que "no tenía cómo medirse" era FP-08, y se resolvió
agregando `segment`. El alcance pasó de 9/11 a **10/11**.

**El motivo de excluir FP-10 cambió.** No es que falten etiquetas: su evidencia es
búsqueda web real, no reproducible entre corridas. Limitación más fuerte para el
entregable 7, y registrada en
[ADR-0005](../adr/0005-exclusion-de-fp-10-por-evidencia-no-reproducible.md).

Corolario: **`issuer_bank` no se modela**. Era su único insumo. Se queda en el CSV.

---

## 8. Mapa de archivos al cierre

```
multiagent-fraud-detection/
├── data/
│   ├── README.md                          # esquema, etiquetas, limitaciones
│   ├── customer_behaviors.csv
│   ├── transactions.csv
│   ├── ground_truth.csv
│   └── policies/fraud_policies_2025.1.json
├── scripts/
│   ├── generate_data.py                   # generador (determinista)
│   ├── build_ground_truth.py              # etiquetas por regla, as-of
│   ├── validate_dataset.py                # gate de CI
│   ├── seed.py                            # adaptador + upsert
│   └── smoke_seed.py                      # 18 comprobaciones
└── src/multiagent_fraud_detection/
    ├── enums.py                           # + Segment
    ├── db/
    │   ├── models/
    │   │   ├── transaction.py             # + 2 índices compuestos
    │   │   ├── customer_behavior.py       # + 7 columnas
    │   │   └── merchant_blacklist.py      # 🆕
    │   └── repositories/                  # 🆕
    │       └── transaction_history.py     # el invariante as-of
    └── schemas/
        ├── types.py                       # + CurrencyCode, TimeZone
        ├── customer_behavior.py           # + 7 campos
        └── merchant_blacklist.py          # 🆕
```

---

## 9. Qué sigue: los agentes de lógica pura

Tres nodos que no necesitan LLM y pueden probarse contra el ground truth de
inmediato: **Transaction Context**, **Behavioral Pattern** y **Evidence
Aggregation**.

Preguntas abiertas para esa conversación:

1. **¿Una política, una función?** Diez reglas puras que reciben transacción,
   perfil e historial y devuelven señales. ¿Módulo por política, o un catálogo
   con despacho por identificador?
2. **`build_ground_truth.py` ya implementa las diez reglas.** ¿Se extrae a
   `domain/policies.py` y lo importan tanto el script como los agentes, o se
   mantienen dos implementaciones a propósito para que el harness no valide el
   sistema contra sí mismo?
3. **Dónde entra `merchant_blacklist` en el grafo**: consulta por nodo o cacheada
   en memoria con invalidación, como manda §4 para el allowlist.
4. **El reparto Context vs Behavioral.** Cuatro políticas necesitan historial
   (secuencia), cinco necesitan perfil, una necesita solo la transacción. La
   frontera entre los dos agentes no es obvia.
5. **La confianza determinística**: cómo se compone el score desde las señales
   producidas, antes de que el Arbiter lo ajuste.
6. **Muestreo estratificado para el harness**: 300 casos al azar sobre 7 000 dan
   ~3 de FP-01 y probablemente cero nocturnos. El seed no crea casos a propósito;
   quién los crea y con qué criterio se decide ahí.

### Después de los agentes puros

RAG de políticas (pgvector ya habilitado) → allowlist y búsqueda web gobernada →
agentes con LLM (Debate ×2, Arbiter, Explainability) → API FastAPI + HITL →
harness de evaluación (entregable 7) → CI (entregable 5).

---

## 10. Documentación asociada

- `contrato_de_interfaz.md` **v0.5** — §1.4 (tres entornos, TLS, Postgres 18),
  §2.2 (precedencia), §2.5 (siete campos), §2.7 (muere `America/Lima`),
  §7.1 (`merchant_blacklist`), §7.7 (invariante *as-of*).
- [ADR-0003](../adr/0003-dataset-sintetico-como-instrumento-de-evaluacion.md) —
  el dataset como instrumento de evaluación.
- [ADR-0004](../adr/0004-consultas-de-historial-as-of.md) — consultas *as-of*.
- [ADR-0005](../adr/0005-exclusion-de-fp-10-por-evidencia-no-reproducible.md) —
  exclusión de FP-10.
- [`data/README.md`](../../data/README.md) — el dataset en detalle.
- [`03-grafo-y-persistencia.md`](03-grafo-y-persistencia.md) — etapa anterior.
