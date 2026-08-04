# Catálogo de políticas — documento, vinculación y predicados

> Especificación de la capa de reglas del motor determinístico: cómo un documento
> normativo del banco se vuelve evaluable sin dejar de pertenecerle al banco.
>
> Decisión de fondo: [ADR-0007](adr/0007-la-forma-ejecutable-de-una-politica-es-una-vinculacion.md).
> Reparto determinístico/LLM: [ADR-0006](adr/0006-reparto-deterministico-y-llm.md).

---

## 1. Tres artefactos, tres dueños

```
  documento normativo          vinculación              biblioteca de predicados
   (lo escribe el banco)     (la escribimos nosotros)      (código, cerrada)

   FP-01                 ←──── FP-01 →  amount_over_avg_multiple(3)  ──→  función
   "monto > 3x el                       outside_usual_hours()        ──→  función
    promedio habitual
    y horario fuera
    de rango"
```

El documento es prosa con autoridad. La biblioteca es código. **La vinculación es
el puente**: lo único que decide qué predicado, con qué parámetro, corresponde a
esa norma.

Que sea un objeto propio es deliberado. El texto dice *"promedio habitual"*; que
eso se compare contra `usual_amount_avg` y no contra el promedio del segmento **es
una interpretación**, y el texto no la resuelve —el sistema tiene ambos valores, y
FP-08 usa el segundo—. Un acto de interpretación tiene autor y fecha, igual que
una migración.

> **La traducción solo existe para políticas que llegan de afuera.** Una política
> que nace en el dashboard captura texto y condición en el mismo acto. El archivo
> de vinculaciones es el **seed** de las once del enunciado, no un flujo de
> trabajo permanente.

---

## 2. El documento normativo

`data/policies/fraud_policies_2025.1.json`, **exactamente como está hoy**. No se
edita, no se le agregan campos, no se le cambia el nombre a `rule`.

```json
{
  "policy_id": "FP-01",
  "rule": "Monto > 3x promedio habitual y horario fuera de rango -> CHALLENGE",
  "version": "2025.1"
}
```

Es el corpus del RAG. En un despliegue real no serían once líneas sino circulares
y manuales; por eso `InternalCitation` tiene `chunk_id`.

---

## 3. La vinculación

`data/policies/policy_bindings_2025.1.json`. Un registro por política.

**Encabezado** (envoltura del archivo):

| Campo | Ejemplo | Notas |
|---|---|---|
| `binding_set_version` | `2025.1-b1` | valor que se sella en `policy_catalog_version` |
| `source_catalog` | `fraud_policies_2025.1.json` | de qué documento derivan |
| `fingerprint_algorithm` | `sha256` | |
| `fingerprint_field` | `rule` | **solo el texto**, no el objeto completo |
| `reference_currency` | `USD` | moneda de todo umbral monetario |

El sufijo `-bN` versiona las traducciones por separado del documento: si el banco
no cambia nada pero se corrige una interpretación, sube a `-b2`.

Se hashea `rule` y no el objeto entero para que un typo corregido en `version` no
invalide una traducción que sigue siendo correcta.

**Cada vinculación**:

| Campo | Tipo | Notas |
|---|---|---|
| `policy_id` | `str` | apunta al documento |
| `source_version` | `str` | versión del documento traducido |
| `source_fingerprint` | `str` | `sha256:…` del texto normativo |
| `action` | `DecisionType` | `CHALLENGE` \| `BLOCK` \| `ESCALATE_TO_HUMAN`. Nunca `APPROVE` |
| `condition` | `list[Predicate] \| null` | conjunción (AND). `null` solo con `excluded_reason` |
| `excluded_reason` | `str` | por qué no se traduce. **Obligatorio si `condition` es `null`** |
| `active` | `bool` | bandera de gobernanza |
| `bound_by` | `str` | quién hizo la traducción |
| `bound_at` | `datetime` | cuándo |

Cada elemento de `condition`:

```json
{ "predicate": "amount_over_avg_multiple", "params": { "factor": 3 } }
```

Cuatro campos **derivados** que no se escriben —los calcula el loader—, porque un
campo redundante que alguien puede editar mal es una fuente de verdad de más:

| Derivado | De dónde sale |
|---|---|
| `requires` | unión de los insumos de sus predicados |
| `owner` | `context` si no incluye perfil ni historial; `behavioral` si sí |
| `signals` | los códigos de señal de sus predicados |
| `evaluable` | `active` ∧ `condition is not null` ∧ huella vigente |

---

## 4. Los cuatro estados de una política

| Estado | Cuándo | RAG | Motor |
|---|---|---|---|
| **Activa** | vinculación con huella vigente | cita | evalúa |
| **Excluida** | `condition: null` + `excluded_reason` | cita | no evalúa |
| **Pendiente** | documento sin vinculación | cita | no evalúa |
| **Obsoleta** | la huella dejó de coincidir | cita el texto **nuevo** | no evalúa |

Los tres últimos **no son errores**: son estados operativos que el sistema
reporta y el dashboard muestra.

*Excluida* y *pendiente* se separan a propósito: FP-10 no está traducida **por
decisión** (ADR-0005), no por falta de tiempo. Sin la distinción, la métrica de
políticas sin traducir marcaría 1 para siempre y nadie miraría una alarma que
nunca baja a cero.

Ante una vinculación obsoleta se **degrada** —deja de evaluarse, sigue siendo
citable— por coherencia con la decisión 12 del contrato, y para que un editor
externo no pueda dejar el motor fuera de servicio con un cambio de redacción.

Dos métricas operativas para el entregable 6: **políticas pendientes** y
**vinculaciones obsoletas**.

---

## 5. La biblioteca de predicados

Catorce predicados. **Esto es lo que vive en código**, y crece solo con un
despliegue.

Cada uno declara sus insumos, su código de señal y su severidad. La severidad va
en el predicado y no en la política porque `Signal.severity` califica la
observación, no la norma: *"dispositivo nuevo"* pesa igual esté en FP-02 o en la
política que se escriba mañana.

> **Los predicados deben ser introspectables.** Cada parámetro se declara como
> dato —nombre, tipo, rango, etiqueta legible—, no solo como firma de Python, para
> que `GET /api/v1/predicates` alimente el compositor del dashboard sin mantener
> una lista duplicada en el frontend.

### 5.1 Comparación puntual (transacción + perfil)

| Predicado | Params | Insumos | Señal | Sev. |
|---|---|---|---|---|
| `amount_over_avg_multiple` | `factor` | tx, perfil | `AMOUNT_OVER_USUAL_AVG` | medium |
| `amount_over_absolute` | `threshold_ref` | tx, fx | `AMOUNT_OVER_ABSOLUTE` | low |
| `outside_usual_hours` | — | tx, perfil | `OUTSIDE_USUAL_HOURS` | medium |
| `country_not_usual` | — | tx, perfil | `FOREIGN_COUNTRY` | medium |
| `device_not_usual` | — | tx, perfil | `NEW_DEVICE` | medium |
| `channel_not_usual` | — | tx, perfil | `NEW_CHANNEL` | low |
| `account_age_below` | `days` | tx, perfil | `NEW_ACCOUNT` | low |
| `amount_over_segment_multiple` | `factor` | tx, perfil, stats | `AMOUNT_OVER_SEGMENT_AVG` | medium |
| `profile_changed_within` | `minutes` | tx, perfil | `RECENT_PROFILE_CHANGE` | high |

`outside_usual_hours` resuelve la ventana en la **zona del perfil** y contempla el
cruce de medianoche. Es el único predicado cuya lógica ya causó un bug documentado
—el supuesto `America/Lima`—, así que va con test propio.

Todo umbral monetario se expresa en **moneda de referencia** y se convierte con la
tabla FX. Nunca literales.

### 5.2 Lookup en tabla de gobernanza

| Predicado | Params | Insumos | Señal | Sev. |
|---|---|---|---|---|
| `merchant_blacklisted` | — | tx, blacklist | `MERCHANT_BLACKLISTED` | high |

### 5.3 Secuencia (historial *as-of*)

| Predicado | Params | Insumos | Señal | Sev. |
|---|---|---|---|---|
| `count_in_window` | `axis`, `window_minutes`, `min_count` | historial(eje) | `DEVICE_VELOCITY` / `CUSTOMER_VELOCITY` | high |
| `preceding_micro_charges` | `min_count`, `ceiling_ref`, `window_minutes` | historial(cliente), fx | `MICRO_CHARGE_SEQUENCE` | high |
| `distinct_country_in_window` | `window_minutes` | historial(cliente) | `IMPOSSIBLE_TRAVEL` | high |
| `daily_sum_over_limit` | `group_by`, `min_count` | historial(cliente), perfil | `DAILY_LIMIT_EXCEEDED` | high |

Los cuatro consultan historial **exclusivamente** por
`db/repositories/transaction_history.py`, donde vive el invariante *as-of*
([ADR-0004](adr/0004-consultas-de-historial-as-of.md)). El `as_of` **no es
parámetro de la vinculación**: lo fija el motor con el timestamp de la transacción
bajo análisis. Exponerlo sería permitir que una política pida ver el futuro.

`count_in_window` produce un código de señal distinto según el eje. El mapa
`(predicado, eje) → código` vive en código: si fuera campo libre, el vocabulario
que el entregable 6 vigila lo escribiría quien traduce una política.

---

## 6. Las once políticas

| ID | Condición | Acción | Dueño |
|---|---|---|---|
| FP-01 | `amount_over_avg_multiple(3)` ∧ `outside_usual_hours()` | CHALLENGE | behavioral |
| FP-02 | `country_not_usual()` ∧ `device_not_usual()` | ESCALATE_TO_HUMAN | behavioral |
| FP-03 | `count_in_window(axis=device, window=5, min_count=4)` | BLOCK | behavioral |
| FP-04 | `preceding_micro_charges(2, ceiling_ref=1.0, window=10)` ∧ `amount_over_avg_multiple(2)` | BLOCK | behavioral |
| FP-05 | `distinct_country_in_window(window=120)` | ESCALATE_TO_HUMAN | behavioral |
| FP-06 | `channel_not_usual()` ∧ `amount_over_avg_multiple(2)` | CHALLENGE | behavioral |
| FP-07 | `merchant_blacklisted()` ∧ `amount_over_absolute(135.0)` | ESCALATE_TO_HUMAN | **context** |
| FP-08 | `account_age_below(30)` ∧ `amount_over_segment_multiple(5)` | ESCALATE_TO_HUMAN | behavioral |
| FP-09 | `profile_changed_within(30)` | BLOCK | behavioral |
| FP-10 | *excluida* — ADR-0005 | — | — |
| FP-11 | `daily_sum_over_limit(group_by=merchant, min_count=3)` | BLOCK | behavioral |

Tres lecturas:

**El reparto Context / Behavioral es 1 contra 9, y no lo elegimos.** Se deriva de
los insumos, y coincide exactamente con la rama `if perfil is None` de
`build_ground_truth.py`, que evalúa solo FP-07 para las ~96 transacciones sin
perfil. La respuesta a la pregunta 4 del acta 04 estaba en el etiquetador.

**Context no es un agente anémico: es el piso de evidencia.** Es el único que
sigue produciendo señales cuando el cliente no existe —el escenario que el
contrato v0.3 llamó *"el que más importa"*—.

**Ninguna política cruza los dos nodos.** Por eso la conjunción la evalúa el
agente dueño y no Aggregation: así el RAG, que corre después de la ola 1, ve las
políticas ya disparadas y puede afinar su query. Que ninguna cruce hoy es
verificable, así que se convierte en **validación estructural**.

---

## 7. Lo que se valida al cargar

Con reglas como dato, la validación se corre de compilación a carga. Esto la
reemplaza:

1. Todo `predicate` existe en la biblioteca.
2. Los `params` coinciden con la firma —nombres, tipos y rangos—.
3. `action` ∈ `DecisionType`, nunca `APPROVE`.
4. `condition: null` exige `excluded_reason`.
5. `policy_id` de la vinculación existe entre los documentos.
6. `source_fingerprint` coincide con el texto vigente → si no, estado **obsoleta**.
7. Ninguna política evaluable abarca los dos nodos (§6).
8. **Gate de CI**: evaluar el catálogo completo sobre las 7 000 transacciones
   reproduce `ground_truth.csv` **exactamente**.

El punto 8 es lo que da valor a toda la etapa: dos implementaciones independientes
—el etiquetador escrito a mano y el intérprete— que coinciden en 7 000 filas son
evidencia fuerte de que ambas están bien.

---

## 8. Lo que **no** es política

Tres cosas que parecen catálogo y no lo son. Van a `domain/params.py`, versionadas
aparte, porque no las escribe cumplimiento y una discrepancia en ellas no es un
hallazgo sino ruido:

| Parámetro | Qué es | Por qué no es política |
|---|---|---|
| Tabla FX | factores a moneda de referencia | atributo del mundo, no norma |
| Promedios por segmento | `retail 634.35` · `premium 1847.59` · `business 4778.64` (USD) | agregado poblacional, insumo de FP-08 |
| Precedencia | `BLOCK > ESCALATE_TO_HUMAN > CHALLENGE > APPROVE` | meta-regla de resolución de conflictos |

**Los promedios por segmento se congelan, no se consultan.** Calculados en runtime
se mueven con la población y hacen irreproducible el harness sin que nada falle;
además el perfil es mutable, así que consultarlos viola el espíritu del invariante
*as-of*. Se sellan bajo `scoring_version`.

---

## 9. Decisiones abiertas 🔶

| # | Decisión | Propuesta |
|---|---|---|
| 1 | **Eje de FP-03**: el repositorio consulta por dispositivo cruzando cuentas; `build_ground_truth.py` filtra por cliente **y** dispositivo | `axis=device`, cross-customer. Verificado: 1 337 dispositivos, 27 compartidos, 77 transacciones, **cero divergencia** entre criterios (59 positivos idénticos) |

---

## 10. Fases

| Fase | Qué | Dónde |
|---|---|---|
| **1 — Parametrizar** | umbrales, FX, promedios y precedencia salen del código | esta rama |
| **2 — Vincular** | vinculaciones como dato + intérprete + validador + huellas | esta rama |
| **3 — Gobernar** | dos tablas (`fraud_policies`, `policy_bindings`) + vista de políticas en el dashboard | rama posterior |

La fase 3 queda fuera de esta rama a propósito: entra **con su consumidor** —el
RAG, que lee los documentos desde la base para indexarlos—, por el mismo criterio
con el que se difirió `web_search_allowlist`.