# Dataset sintético — detección de fraude

Tres archivos generados por script, reproducibles byte a byte. No son datos de
muestra para poblar la base: son el **instrumento de evaluación** del entregable 7.

```bash
uv run python scripts/generate_data.py       # → customer_behaviors.csv, transactions.csv
uv run python scripts/build_ground_truth.py  # → ground_truth.csv
uv run python scripts/validate_dataset.py    # verifica los tres; código ≠ 0 si falla
```

El orden importa: el ground truth se calcula **sobre** el dataset, y el validador
comprueba los tres juntos.

---

## 1. Los tres archivos

| Archivo | Filas | Qué es |
|---|---|---|
| `customer_behaviors.csv` | 1 000 | Perfil de comportamiento por cliente |
| `transactions.csv` | 7 000 | Transacciones de diciembre 2025 |
| `ground_truth.csv` | 7 000 | Etiqueta esperada por transacción |
| `policies/fraud_policies_2025.1.json` | 11 | Catálogo de políticas, insumo del RAG |

`ground_truth.csv` es un archivo **aparte** a propósito: el sistema bajo
evaluación nunca lo ve. Solo lo carga el harness. Si las etiquetas fueran
columnas de `transactions.csv`, el seed tendría que cargarlas —y entonces la
respuesta estaría al alcance de cualquier agente que consulte historial— o
descartarlas en silencio.

---

## 2. `customer_behaviors.csv`

| Columna | Tipo | Notas |
|---|---|---|
| `customer_id` | `CU-0001` … `CU-1000` | ancho fijo |
| `usual_amount_avg` | decimal | en la moneda de la cuenta |
| `usual_hours` | `"08-20"` | **hora local**, `[inicio, fin]` inclusive |
| `usual_countries` | lista `;` | puede venir **vacía** |
| `usual_devices` | lista `;` | puede venir **vacía** |
| `usual_channel` | `web` \| `mobile` | singular, no lista (§6) |
| `account_creation_date` | `YYYY-MM-DD` | |
| `last_profile_update` | ISO local | |
| `issuer_bank` | `BCP`, `JPM`, … | **no se modela** (§5) |
| `daily_limit` | decimal | misma moneda |
| `currency` | ISO 4217 | constante por cliente |
| `timezone` | IANA | `America/Lima`, `Europe/Madrid`, … |
| `segment` | `retail` \| `premium` \| `business` | |

**`usual_hours` cruza medianoche.** Un cliente nocturno (`22-06`) es válido:
`inicio > fin` no es un error, y la comparación tiene que contemplarlo. 49
perfiles lo hacen.

**Una lista vacía no es un dato faltante.** "Ningún dispositivo habitual"
significa que *todo* dispositivo es nuevo → eso es señal, no hueco. 27 perfiles
sin dispositivo, 29 sin país.

**`segment` multiplica el monto** (retail ×1, premium ×3, business ×8). Sin esa
separación el promedio del segmento sería el promedio global, y FP-08 —"> 5× el
promedio de su segmento"— no se distinguiría de "5× su propio promedio".

---

## 3. `transactions.csv`

| Columna | Notas |
|---|---|
| `transaction_id` | `T-1001`…, único, **no consecutivo** (los grupos saltan) |
| `customer_id` | ~96 filas apuntan a clientes **sin perfil** |
| `amount` | en la moneda de la cuenta |
| `currency` | la del perfil, no la del país de la compra |
| `country` | país donde ocurre la compra |
| `chanel` | *(sic)* typo heredado del enunciado del reto |
| `device_id` | |
| `timestamp` | **UTC con offset** (`+00:00`) |
| `merchant_id` | `M-999` es el comercio en lista negra |
| `issuer_bank` | |

**La moneda es de la cuenta, no del país.** Una tarjeta liquida en la moneda de
su cuenta. La dimensión internacional sobrevive porque `country` sigue variando.

**El timestamp se construye en hora local del cliente y se emite en UTC.** Esto
es lo que le da sentido a `timezone`: un agente que interprete el timestamp como
si fuera hora local **clasifica mal 2 227 de 6 904 transacciones** (32%).

**`chanel` se deja con el typo.** Renombrar una columna es traducción de forma
pura: o el mapeo existe o revienta ruidosamente. Se corrige en el adaptador del
seed, no en la fuente.

---

## 4. `ground_truth.csv`

| Columna | Notas |
|---|---|
| `transaction_id` | clave |
| `expected_policies` | lista `;`, vacía si ninguna aplica |
| `expected_decision` | `APPROVE` \| `CHALLENGE` \| `BLOCK` \| `ESCALATE_TO_HUMAN` |
| `fraud_group_id` | lista `;` — una transacción puede estar en dos grupos |
| `is_closing` | `true` en la que completa un patrón |

Hay una fila **por cada** transacción, incluidas las limpias: sin etiqueta
negativa se puede calcular recall, pero no precisión.

### Positivos por política

| | | | |
|---|---|---|---|
| FP-01 | 61 | FP-06 | 57 |
| FP-02 | 79 | FP-07 | 80 |
| FP-03 | 59 | FP-08 | 66 |
| FP-04 | 59 | FP-09 | 69 |
| FP-05 | 71 | FP-11 | 66 |

`APPROVE` 6 347 · `ESCALATE_TO_HUMAN` 286 · `BLOCK` 252 · `CHALLENGE` 115.

Cada política supera los 55 positivos. Por debajo de ~30, un solo error mueve el
F1 varios puntos y la métrica deja de significar algo.

### Las tres reglas de etiquetado

**Se etiqueta por la regla, no por la intención del generador.** El generador sabe
qué rama sorteó, pero esa información se descarta. Con confusores en el dataset,
un patrón "normal" puede satisfacer una política por accidente. Prueba de que el
criterio era necesario: **14 transacciones satisfacen dos políticas a la vez**
(`FP-02;FP-05` es la más común). Etiquetadas por rama, esas 14 estarían mal
marcadas y el harness castigaría al sistema por acertar.

**Se evalúa *as-of*, nunca con el futuro.** Cada regla mira solo hacia atrás. En
una ráfaga de cuatro, solo la cuarta lleva `FP-03`; las tres anteriores son
`APPROVE` con `fraud_group_id`. Cuando llegó la primera, el patrón todavía no
existía y aprobarla era correcto.

> Corolario para el grafo: toda consulta de historial lleva
> `WHERE timestamp <= :as_of`, donde `as_of` es el timestamp de la transacción
> bajo análisis — **nunca `now()`**. Un agente que no filtre funciona bien en
> producción (el futuro no está en la tabla) y solo falla en evaluación, inflando
> sus propias métricas.

**Cuando dos políticas aplican, gana la más restrictiva**:
`BLOCK > ESCALATE_TO_HUMAN > CHALLENGE > APPROVE`. El Arbiter tiene que usar la
misma precedencia, o la comparación contra el ground truth es injusta.

---

## 5. Alcance: 10 de 11 políticas

**FP-10** (alerta pública sobre el emisor/BIN) queda fuera. No es falta de
esfuerzo: su evidencia es búsqueda web real, no reproducible entre corridas. Si
se inventan nombres de banco, ninguna alerta existe; si se usan bancos reales, el
resultado cambia de un día para otro y la etiqueta deja de ser verdad estable.

> **Una política cuya evidencia no es reproducible no es evaluable en un harness.**

Su rama se conserva en el generador —quitarla correría el stream de números
aleatorios—, pero `validate_dataset.py` falla si `FP-10` aparece en las etiquetas.

Corolario: **`issuer_bank` no se modela**. Era el insumo de FP-10 y de nada más.
Se queda en el CSV como dato de origen. Modelarlo es una migración de una línea
el día que exista un proveedor de alertas real (entregable 10).

---

## 6. Confusores: por qué el dataset no es solo "datos"

La versión original tenía las tres dimensiones de decisión como **predictores
perfectos**: ninguna transacción con país, dispositivo o canal distinto del
habitual era legítima. La regla `país ≠ habitual → fraude` tenía precisión 1.0.
No porque fuera buena, sino porque el dataset hacía imposible el falso positivo:
la clase que la precisión mide no existía.

Se agregaron ocho confusores, tallados del relleno (el total sigue en 7 000):

**Señal suelta legítima** — dispara una dimensión, ninguna política:

| | Por qué no dispara |
|---|---|
| Viaje legítimo | FP-02 exige internacional **y** dispositivo nuevo |
| Teléfono nuevo en casa | FP-02 exige que además sea internacional |
| Canal distinto, monto normal | FP-06 exige monto > 2× |
| Compra grande en horario habitual | FP-01 exige monto **y** horario |

**Casi-positivo** — falla una condición por poco:

| | Por qué no dispara |
|---|---|
| 3 tx en 6 min | FP-03 exige más de 3 en menos de 5 |
| Centavos sin el monto de cierre | FP-04 exige el cobro grande |
| Pagos que suman 0.9× el límite | FP-11 exige superarlo |
| Cuenta de 31-60 días con 6× | FP-08 exige menos de 30 |

Resultado:

| Dimensión | Activan | Legítimas | Antes |
|---|---|---|---|
| país ≠ habitual | 503 | 424 (84%) | 0 |
| dispositivo ≠ habitual | 640 | 218 (34%) | 0 |
| canal ≠ habitual | 127 | 70 (55%) | 0 |
| monto > 3× | 342 | 281 (82%) | 0 |

El `if` de una línea pasó de precisión 100% a 16%.

---

## 7. Casos límite deliberados

El contrato declara válidos varios escenarios que el dataset original no
ejercitaba en absoluto:

| Caso | Cantidad | Qué prueba |
|---|---|---|
| Clientes nocturnos (`22-06`) | 49 | Cruce de medianoche |
| `usual_devices` vacío | 27 | "Todo dispositivo es nuevo" como señal |
| `usual_countries` vacío | 29 | Idem países |
| Perfiles multi-país | 23 | Lista de verdad, no escalar |
| Transacciones **sin perfil** | ~96 | `CaseDetail.customer = null` |

El último es el que v0.3 llamó *"el escenario que más importa"*: un cliente sin
historial no es un error, es el caso más sospechoso. El generador les asigna
identificadores del rango `CU-9xxx`, que no existe en `customer_behaviors.csv`.

---

## 8. Reproducibilidad

`np.random.seed(42)` usa el `RandomState` legado, cuyo stream numpy congeló por
política de compatibilidad. Verificado: los tres CSV salen **idénticos byte a
byte** entre corridas y entre versiones distintas de numpy y pandas.

Eso hace del diff byte a byte una guarda real de CI, no una curiosidad:

```bash
uv run python scripts/generate_data.py && git diff --exit-code data/
```

---

## 9. Supuestos y limitaciones

- **Cuentas mono-moneda.** Una cuenta liquida siempre en la misma moneda. Fuera
  de alcance: cuentas multi-moneda y conversión FX.
- **Tipos de cambio fijos**, aproximados y sin variación temporal. Sirven para
  que los umbrales monetarios sean comparables entre países, no para contabilidad.
- **Ventana de un mes** (diciembre 2025). Suficiente para las políticas de
  secuencia; delgada para un agente que quiera calcular su propia línea base de
  30 días —para eso está `usual_amount_avg` precalculado en el perfil—.
- **~7 transacciones por cliente.** No es densidad realista de un banco; es la
  densidad que hace que 7 000 filas alcancen para 1 000 perfiles.
- **Las etiquetas humanas del sistema** (tabla `human_resolutions`) vienen solo de
  casos escalados —por construcción, los ambiguos—. Ese ground truth está sesgado
  por muestreo y no es intercambiable con este archivo.
- **`transaction_id` no es consecutivo**: los patrones multi-transacción reservan
  identificadores en bloque. Solo se garantiza unicidad.

---

## 10. Muestreo para el harness

Evaluar las 7 000 no es viable: correr el grafo son llamadas a LLM. El harness
toma una muestra de 200–300 casos, y tiene que ser **estratificada**: 300 al azar
sobre 7 000 darían ~3 casos de FP-01 y probablemente cero clientes nocturnos.

El seed carga **historial** (transacciones y perfiles) y **no crea casos**. Crear
un caso es correr el pipeline: eso lo hace el `POST /cases` o el harness.