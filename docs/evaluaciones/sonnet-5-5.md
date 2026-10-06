# Evaluación: ¿migrar de Sonnet 5 a Sonnet 5.5?

> Fecha: 2026-10-05. Medido sobre los mismos estados que la
> [evaluación de Jev](jev-como-arbitro.md) y que la medición del presupuesto de
> tokens de [ADR-0031](../adr/0031-el-razonamiento-es-explicito-y-el-tope-lo-cubre.md).

## Conclusión

**No migrar todavía.** Sonnet 5.5 decide igual que Sonnet 5 en este proyecto, pero
no resultó más rápido ni más barato. Sonnet 5 sigue activo hasta, como mínimo, el
30/06/2027. Desde ADR-0031, migrar es cambiar constantes, así que conviene
hacerlo cuando una medición muestre una ganancia.

## Lo que cambia en Sonnet 5.5 (documentación de Anthropic)

| Cambio | Para este proyecto |
|---|---|
| Mismo precio y tokenizer | Mismo costo por token |
| "30 %+ más rápido, hasta 30 % menos tokens" | No se reprodujo (abajo) |
| `thinking: disabled` devuelve 400; el reemplazo es `between_tools` | El debate y la explicación tendrían que usarlo. Un test obliga a revisarlo si cambia el modelo |
| Razonamiento adaptativo por defecto, con `effort` recalibrado | Hay que volver a medir; no se trasladan configuraciones |
| `tool_choice` forzado devuelve 400 | No se usa |
| Puede rechazar un pedido (`stop_reason: refusal`) | Desde ADR-0031, todo lo que no sea `end_turn` es un error |

## Medición

**Árbitro** (razonamiento adaptativo, 2 000 tokens):

| Conjunto | Acuerdo con Sonnet 5 | Escaladas de Sonnet 5 que 5.5 también hace |
|---|---|---|
| Producción (20 casos, incluida la escalada real) | 20/20 | 1/1 |
| Casos difíciles construidos (12) | 11/12 | 7/7 |

La diferencia: en un caso con un argumento del debate que afirmaba hechos que no
estaban entre las señales, Sonnet 5.5 los dio por evidencia y subió a CHALLENGE.

**Velocidad y tokens, en las mismas condiciones:**

| | Sonnet 5 | Sonnet 5.5 |
|---|---|---|
| Latencia del árbitro (mediana, 11 casos) | 3,83 s | 4,01 s |
| Latencia del debate (mediana, 8 llamadas) | 3,0 s | 3,2 s |
| Tokens de salida del árbitro | base | −4 % |
| Tokens de salida del debate | base | +14 % |

Con el `effort` por defecto (`high`) no hubo ganancia. Bajarlo podría acelerar,
pero con menos razonamiento el árbitro omitía escaladas (ADR-0031), así que
habría que medirlo aparte.

## La medición del presupuesto de tokens (Sonnet 5)

Es la medición que fijó la configuración de ADR-0031, sobre los mismos casos
difíciles:

| Nodo | Con razonamiento adaptativo | Sin razonamiento |
|---|---|---|
| Árbitro | 7 de 7 escaladas; hasta 950 tokens de salida | **Omitió 3 de 7 escaladas** |
| Debate | No razonó en ningún caso (máx. 292 tokens) | Equivalente |
| Explicación al cliente | Una de BLOCK razonó y llegó a 425, sobre el tope de 400 | Sin cortes |

De ahí la configuración: razonamiento adaptativo con 2 000 tokens en el árbitro;
sin razonamiento en el debate (600) y en la explicación (400).

## Cuándo revisarlo

Antes de junio de 2027, cuando Sonnet 5 se acerque al retiro, o si una medición
con otro `effort` muestra una ganancia real.

## Fuentes

- [What's new in Claude Sonnet 5.5](https://platform.claude.com/docs/en/models/sonnet-5-5/whats-new-sonnet-5-5)
- [Migrating to Claude Sonnet 5.5](https://platform.claude.com/docs/en/models/sonnet-5-5/migration-guide)
- [Model deprecations](https://platform.claude.com/docs/en/about-claude/model-deprecations)
