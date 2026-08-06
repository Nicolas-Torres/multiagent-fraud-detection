# ADR-0015: la evidencia externa entra al veredicto por el vocabulario del catálogo

- **Estado**: aceptado
- **Fecha**: 2026-08-05
- **Reemplaza a**: [ADR-0005](0005-exclusion-de-fp-10-por-evidencia-no-reproducible.md) — su principio se conserva; su conclusión sobre FP-10 no

## Contexto

[ADR-0014](0014-la-inteligencia-externa-se-recoge-en-build-y-se-consulta-congelada.md)
deja la inteligencia externa disponible como dato congelado y reproducible.
Queda decidir **con qué vocabulario habla**: si emite una señal con código propio,
fuera del catálogo, o si se vincula a la política que ya la nombra.

El árbitro determinístico responde la pregunta antes de que empiece:

```python
"decision": prescribed_action(runtime.context.catalog, tuple(politicas))
```

El veredicto es función **exclusiva** de `matched_policies` y de la precedencia
del catálogo. `risk_score` no entra. `base_confidence` tampoco. Una señal que no
pertenece a ninguna política **no puede cambiar ningún veredicto**: sólo mueve la
confianza.

Sobre un caso limpio —el 90.7% del tráfico— el efecto medido es éste:

| | `risk_score` | `base_confidence` | veredicto |
|---|---|---|---|
| Sin señales | 0.00 | 1.00 | `APPROVE` |
| + una señal externa `HIGH` fuera del catálogo | 0.50 | 0.50 | **`APPROVE`** |

El sistema aprobaría una transacción con un indicador de compromiso activo, y
todo el rastro sería que la confianza cayó a la mitad. Y `base_confidence` tiene
forma de U: mide **ambigüedad**, no riesgo. Un 0.50 ahí dice *"no estoy seguro"*,
no *"hay una alerta"*. La información existe, se registra, y no decide nada.

Peor: esa señal **no violaría** el invariante del contrato, que es de contención
—*"una cita por cada `policy_id` de `matched_policies`"`*— y con `matched_policies`
vacía se cumple vacíamente. No rompe la regla: se queda fuera de su alcance. Una
regla que se elude sin dejar rastro es peor que una que se viola.

FP-10 ya nombra exactamente este caso: *"Alerta externa activa: si hay alertas
públicas de fraude sobre el banco emisor o BIN en últimas 24h → CHALLENGE"*.
ADR-0005 la excluyó, y su motivo era único y explícito: la evidencia no era
reproducible entre corridas. ADR-0014 elimina ese motivo.

## Decisión

**La evidencia externa se expresa como política del catálogo.** Se vincula FP-10:
su `condition` deja de ser `null`, `excluded_reason` pasa a `null`, y su
`PolicyState` va de `EXCLUDED` a `ACTIVE` — todo derivado al cargar, sin escribir
nada, tal como fijó [ADR-0007](0007-la-forma-ejecutable-de-una-politica-es-una-vinculacion.md).

**El documento del banco no se toca y la huella sigue válida.** Vincular una
política excluida es precisamente la operación para la que ADR-0007 separó
documento de vinculación: no hay reescritura, no hay `source_fingerprint` roto, no
hay trazabilidad de citación comprometida.

La cadena queda completa y el invariante se satisface por construcción:

```
threat_indicators → EvalContext.indicators (Input nuevo)
  → predicado issuer_under_alert → Hit
    → señal ISSUER_UNDER_ALERT (MEDIUM) + matched_policies = ["FP-10"]
      → bloque de autorización del RAG: cita por identidad (ADR-0011)
        → citations_internal += FP-10 v2025.1
          → prescribed_action → CHALLENGE
```

**Se crea un tercer `Owner`: `THREAT_INTEL`.** Un predicado que pide el insumo
`indicators` hace que su política sea de ese agente. La derivación de `owner`
pasa de binaria a tres ramas, con precedencia explícita: `indicators` gana sobre
la partición contexto/comportamiento.

El motivo es de honestidad de datos, no de estética: `WorkingSignal.emitted_by`
es lo que el harness usa para atribuir falsos positivos. Si la evidencia externa
la evaluara el Transaction Context Agent, ese campo mentiría en el único lugar
donde se lo consulta para medir.

**FP-10 queda activa y no medida.** El ground truth no la contempla y no se
regenera. Su F1 no existe, y el informe del entregable 7 la reporta como *"sin
ground truth reproducible"*, nunca como recall 0.

## Alternativas descartadas

**Señal con código propio, fuera del catálogo.** Es la opción que no toca nada
medido, y por eso es tentadora con el plazo encima. Se descarta porque no puede
cambiar un veredicto —lo demuestra la tabla de arriba— y porque elude el
invariante en vez de someterse a él. Sería construir el agente y dejarlo sin voz.

**Escalar cuando la confianza cae por debajo de un umbral.** Sería el parche que
rescata la alternativa anterior. Se descarta por lo que el propio contrato fija
dos párrafos antes del invariante: *"el veredicto no sale de umbralizar un score:
sale de la política que aplica"*. Además `base_confidence` mide ambigüedad, así
que el umbral dispararía en los casos equivocados.

**Redefinir FP-10 con otro texto y conservar el ID.** Rechazado ya por ADR-0005 y
sigue rechazado: los identificadores del catálogo son referencias de citación, y
reescribir el texto conservando el ID rompe lo que `InternalCitation.version`
existe para dar. Acá no hace falta: el texto de FP-10 describe exactamente lo que
el sistema va a hacer.

**Regenerar el dataset con etiquetas de FP-10.** Le daría métrica dura. Se
descarta por costo y por riesgo: ADR-0005 ya advirtió que tocar la rama del
generador corre el stream aleatorio y cambia las 7 000 filas. Se pagaría el
rehacer todo el harness por una política que igual mediría una prueba de
pertenencia, que es un `in` sobre un conjunto.

## Consecuencias

**El gate sigue en 7 000/7 000, y por una propiedad del dato, no de la
configuración.** FP-10 evalúa una ventana de 24 h resuelta *as-of* contra el
`timestamp` de la transacción ([ADR-0004](0004-consultas-de-historial-as-of.md)).
Las 7 000 transacciones son de diciembre de 2025; cualquier indicador capturado
hoy queda a ocho meses. **FP-10 no puede disparar sobre el dataset aunque la tabla
esté llena.** `check_policies` lo afirma explícitamente en vez de suponerlo: una
invariante que depende de que alguien recuerde el desfase de fechas no es una
invariante.

**`validate_dataset.py` no cambia**: su aserción de que FP-10 nunca aparece en el
ground truth sigue siendo verdadera y sigue siendo útil.

**`PolicyState` no gana un quinto estado.** Sus cuatro valores describen la salud
del vínculo —traducida, huérfana, obsoleta, excluida—, no la cobertura del
dataset. *Evaluable* y *medible* son ejes distintos y mezclarlos volvería el
estado inservible para lo que existe. La consecuencia se absorbe en el informe.

**`issuer_bank` se modela.** La consecuencia de ADR-0005 —*"sería una columna sin
consumidor"*— caducó: ahora tiene uno. Es una migración *expand*, columna nullable
poblada desde `transactions.csv`, que ya la trae.

**`ISSUER_UNDER_ALERT` no entra a `SAFE_THEMES`** y cae al tema genérico. Decirle
al titular que su banco emisor está bajo alerta pública es a la vez revelar
capacidad de detección y hacer una afirmación sobre un tercero identificable. Es
la misma deuda de revisión legal que el acta 06 ya abrió para `MERCHANT_BLACKLISTED`,
y acá se resuelve por omisión deliberada.

**Se conserva de ADR-0005 su principio, que sigue intacto**:

> Una política cuya evidencia no es reproducible no es evaluable en un harness.

Lo que cambió no es el principio: es que apareció el mecanismo que le quita a
FP-10 la no-reproducibilidad. La política pasa de *fuera del alcance implementado*
a *implementada, citable y no medida*. Que una decisión correcta se vuelva
revisable cuando cambia una capacidad es exactamente lo que un ADR existe para
poder contar.
