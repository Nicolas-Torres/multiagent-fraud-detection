# ADR-0033: cada texto o juicio de un LLM que se guarda lleva su versión

- **Estado**: aceptado
- **Fecha**: 2026-10-06

## Contexto

Una decisión guarda cinco sellos de versión: la fórmula de riesgo
(`scoring_version`), el catálogo (`policy_catalog_version`), el índice de
recuperación (`retrieval_index_version`), el prompt de la explicación al cliente
(`explanation_prompt_version`) y el snapshot de inteligencia externa
(`threat_intel_version`).

Tres salidas de un LLM se guardan en la misma decisión **sin versión**:

- el veredicto del árbitro, con su `confidence_rationale`;
- el argumento pro-fraude (`debate_pro_fraud`);
- el argumento pro-cliente (`debate_pro_customer`).

Cada módulo ya declara su `PROMPT_VERSION` (`modelo:plantilla:generación`), pero
nadie lo guarda. En una semana el árbitro pasó por las generaciones 1, 2 y 3
(ADR-0031 y ADR-0032) y el debate por la 1 y la 2. Mirando una decisión no hay
forma de saber cuál de ellas la produjo.

Es el mismo argumento con el que nació `explanation_prompt_version`: editar el
prompt sin subir la generación produce textos distintos bajo la misma versión, y
ninguna consulta lo detecta. Y si no se guarda la generación, subirla tampoco
sirve para auditar.

## Decisión

Tres columnas nuevas en `decisions`, con el formato de
`explanation_prompt_version`:

| Columna | Qué sella |
|---|---|
| `arbiter_prompt_version` | El veredicto y `confidence_rationale` |
| `debate_pro_fraud_prompt_version` | `debate_pro_fraud` |
| `debate_pro_customer_prompt_version` | `debate_pro_customer` |

- **Cada nodo escribe su `PROMPT_VERSION` sólo cuando el LLM respondió.** `null`
  significa que ningún modelo produjo esa salida: el árbitro degradó antes de
  consultarlo o el LLM falló, o el argumento salió del respaldo. Es la misma
  semántica que la de `explanation_prompt_version`.
- **Las decisiones existentes quedan en `null`.** Su fecha permitiría adivinar la
  versión, pero un sello adivinado podría ser falso, y el motivo de sellar es no
  tener que adivinar. La migración es sólo de expansión.
- La API (`DecisionRead`), el dashboard y la explicación de auditoría exponen los
  tres sellos junto a los otros cinco.

## Alternativas descartadas

**Sellar sólo el árbitro.** Cubre el veredicto, pero los argumentos del debate
también se guardan y también alimentan el veredicto: tendrían el mismo hueco.

**Una sola columna con las tres versiones concatenadas.** Ahorra dos columnas,
pero obliga a parsear un texto para consultar una de ellas, y no permite que una
sea `null` (respaldo) sin que lo sean las otras.

**Derivar la versión de la fecha de la decisión y del historial de git.** Viola la
regla del proyecto de no inventar datos, y deja de funcionar si dos versiones
conviven (un deploy en curso, dos nubes con imágenes distintas por minutos).

## Consecuencias

**Se gana**: cada salida de un LLM que queda en la decisión dice qué la produjo.
Un cambio de modelo o de prompt del árbitro (la evaluación de Jev o la de Sonnet
5.5, si alguna hubiera prosperado) queda registrado en cada decisión.

**Se paga**: tres columnas y una enmienda al contrato (§2.5 `Decision`, §7
persistencia), que entra en la v0.17. Las decisiones anteriores al cambio no
tienen estos sellos.
