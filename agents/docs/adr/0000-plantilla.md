# ADR-NNNN: título en una línea, en presente

- **Estado**: propuesto | aceptado | reemplazado por [ADR-NNNN](NNNN-....md)
- **Fecha**: AAAA-MM-DD

## Contexto

Qué situación fuerza la decisión. Restricciones reales: plazo, stack existente,
requisitos de la rúbrica, límites del entorno. Sin justificar todavía.

## Decisión

Qué se hace, en una o dos frases. En presente y en voz activa: *"Se usa una sola
instancia de Postgres"*, no *"se decidió que se usaría"*.

## Alternativas descartadas

Una por bloque, con el motivo del descarte. **Si no puedes nombrar ninguna, el
ADR no se gana el lugar**: no era una decisión, era lo único disponible.

## Consecuencias

Lo que se gana y —sobre todo— lo que se paga. Un ADR que solo lista beneficios
está incompleto: la deuda que se acepta a sabiendas es la parte que el yo del
futuro necesita leer.

---

### Convenciones

- **El número es orden de creación, no de decisión.** La cronología la lleva la
  fecha. Back-fillear decisiones viejas está bien y no altera la numeración.
- **Un ADR aceptado es inmutable.** Si cambias de opinión, escribes uno nuevo y
  marcas el viejo como *reemplazado*. Editar el registro borra el aprendizaje.
- **Una decisión por archivo.** Si el título necesita una "y", probablemente son
  dos ADR.
