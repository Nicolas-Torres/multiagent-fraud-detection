# ADR-0005: se excluye FP-10 porque su evidencia no es reproducible

- **Estado**: aceptado
- **Fecha**: 2026-08-02

## Contexto

El catálogo tiene once políticas, `FP-01` … `FP-11` sin huecos. Diez se evalúan
con datos que el propio dataset contiene. **FP-10** —"alerta pública reciente
sobre el emisor o el BIN"— no: su evidencia es una búsqueda web sobre bancos
reales, ejecutada por el External Threat Intel Agent.

Eso la deja sin ground truth estable:

- Con **nombres de banco inventados**, ninguna alerta real existe y todos los
  casos son negativos. La política nunca dispara y no hay nada que medir.
- Con **bancos reales**, el resultado cambia entre corridas: una alerta indexada
  hoy puede no estarlo mañana. La etiqueta deja de ser verdad y pasa a ser una
  foto del índice de búsqueda en un instante.

Nota histórica: un análisis previo excluyó esta política por otra razón —"el
generador asigna el banco del propio cliente, no hay forma de identificar los
positivos"— y con la numeración corrida, llamándola FP-11. Ambas cosas están
corregidas; la razón de abajo reemplaza a aquella.

## Decisión

FP-10 queda **fuera del alcance implementado**. El sistema evalúa diez de once
políticas.

`validate_dataset.py` falla si `FP-10` aparece en el ground truth: la exclusión es
una invariante verificada, no una nota de intención.

La rama que la genera **se conserva** en el generador aunque produzca
transacciones indistinguibles del relleno. Quitarla correría el stream de números
aleatorios y cambiaría todo el dataset.

## Alternativas descartadas

**Implementarla con un catálogo de alertas fijo, sembrado en la base.** Sería
evaluable, pero mediría la capacidad del sistema de consultar una tabla que
nosotros mismos llenamos —no la de encontrar inteligencia externa—. El agente de
búsqueda web quedaría probado contra un simulacro que garantiza el resultado, que
es la forma más cara de no probar nada.

**Implementarla sin medirla.** Que el agente corra y su salida no entre al
harness. Se descartó porque una política sin métrica en un sistema que reporta
métricas por política es peor que su ausencia: sugiere cobertura donde no la hay.

**Redefinirla para que no dependa de la web** —por ejemplo, "emisor con tasa de
fraude elevada en el propio historial"—. Es una política distinta con el nombre de
FP-10. El catálogo es el insumo del RAG y sus identificadores son referencias de
citación: reescribir el texto y conservar el ID rompe la trazabilidad que
`InternalCitation.version` existe para dar.

## Consecuencias

**Se gana** una limitación bien argumentada para el entregable 7, más fuerte que
"no teníamos el dato". El principio es reutilizable:

> Una política cuya evidencia no es reproducible no es evaluable en un harness.

**`issuer_bank` no se modela.** Era el insumo de FP-10 y de nada más; modelarla
sería una columna sin consumidor. Se queda en `transactions.csv` como dato de
origen. El día que exista un proveedor de alertas real, es una migración de una
línea — y eso es material del entregable 10.

**El External Threat Intel Agent sigue en el sistema.** El reto lo exige y su
salida alimenta `citations_external`. Lo que no se hace es *medirlo contra un
ground truth*: su aporte se evalúa cualitativamente, no con F1.

**Nueve de las diez políticas restantes superan los 55 positivos**, suficiente
para que su F1 signifique algo. Excluir FP-10 no debilita la evaluación: quita de
ella la única política que la habría vuelto no reproducible.
