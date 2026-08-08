"""El prompt del veredicto del Arbiter: la evidencia que el piso no ve, más
el piso mismo.

## El rol en el grafo

`decision_arbiter` reemplaza al brazo de control determinista (ADR-0006,
ADR-0016). El piso —`prescribed_action(catalog, matched_policies)`— sigue
siendo el cálculo que ya vive en `domain/engine.py`; este prompt es lo que el
Arbiter LLM recibe para decidir si se queda ahí o escala.

## Lo que ve que el piso no ve

`prescribed_action` es ciego a todo lo que no sea `matched_policies`: una
señal que la conjunción de una política no cierra —`NO_CUSTOMER_PROFILE`, o
cualquier otra que el motor emitió sin que ninguna política la reúna— no
mueve el piso. Este prompt sí la incluye, junto con los dos argumentos de
debate y los agentes degradados. Es donde vive el "juicio bajo evidencia
contradictoria" que ADR-0006 prometió.

## El piso es una restricción, no una sugerencia

El `SYSTEM_PROMPT` se lo dice al modelo explícitamente, aunque el código
también lo exija después con la cuarta guarda de W2 (ADR-0016): un modelo que
entiende la restricción la viola menos seguido que uno que la descubre por
rechazo.

## El prompt está versionado

Mismo criterio que el resto de los prompts de proveedor: es un parámetro de
derivación, y el segmento de modelo de `PROMPT_VERSION` es una garantía del
proveedor (los IDs de Anthropic desde la generación 4.6 son fijos).
"""

from __future__ import annotations

from collections.abc import Sequence

from multiagent_fraud_detection.enums import DecisionType
from multiagent_fraud_detection.graph.state import WorkingSignal

MODEL = "claude-sonnet-5"
TEMPLATE_TAG = "arbiter-verdict"
GENERATION = 1

PROMPT_VERSION = f"{MODEL}:{TEMPLATE_TAG}:{GENERATION}"

MAX_TOKENS = 500

SYSTEM_PROMPT = """\
Eres el Arbiter de un sistema antifraude: el componente que decide el
veredicto final de una operación, a partir de un piso determinista y de la
evidencia que ese piso no considera.

Reglas que no puedes romper:

1. El piso que se te entrega es una cota mínima de cautela, nunca un punto de
   partida a ignorar. Tu veredicto tiene que ser igual de cauteloso que el
   piso o más — nunca menos. La escala, de más cauteloso a menos, es:
   BLOCK > ESCALATE_TO_HUMAN > CHALLENGE > APPROVE.
2. Usa ÚNICAMENTE la evidencia que se te entrega: señales, políticas
   disparadas, los dos argumentos de debate y qué agentes degradaron. NUNCA
   inventes evidencia ni asumas intención del titular.
3. Súbete por encima del piso sólo cuando la evidencia que el piso no
   considera —una señal aislada, una contradicción entre los argumentos, un
   agente degradado— lo justifique, y explica por qué en `rationale`.
4. Si no hay motivo para apartarte del piso, quédate en él: coincidir con el
   piso también es un veredicto válido, y `rationale` puede ser breve.
5. `confidence` es tu grado de certeza sobre el veredicto, entre 0 y 1. No es
   el puntaje de riesgo: un veredicto puede ser correcto con confianza baja
   si la evidencia es ambigua.
"""


def build_prompt(
    floor: DecisionType,
    evidence: Sequence[WorkingSignal],
    policies: Sequence[str],
    pro_fraud_argument: str,
    pro_customer_argument: str,
    degraded_agents: Sequence[str],
    risk_score: float,
    base_confidence: float,
) -> str:
    """El mensaje de usuario: el piso, la evidencia completa y los dos
    argumentos — todo lo que el Arbiter tiene para decidir."""
    señales = (
        "\n".join(
            f"- {s.code} ({s.severity.value}): {s.description}" for s in evidence
        )
        if evidence
        else "(sin señales)"
    )
    politicas = ", ".join(policies) if policies else "(ninguna política disparó)"
    degradados = ", ".join(degraded_agents) if degraded_agents else "(ninguno)"
    return (
        f"Piso determinista (cota mínima de cautela): {floor.value}\n\n"
        f"Señales detectadas:\n{señales}\n\n"
        f"Políticas que dispararon: {politicas}\n"
        f"Puntaje de riesgo determinístico: {risk_score:.2f}\n"
        f"Confianza determinística base: {base_confidence:.2f}\n"
        f"Agentes degradados durante el análisis: {degradados}\n\n"
        f"Argumento a favor de la cautela:\n{pro_fraud_argument}\n\n"
        f"Argumento a favor de la legitimidad:\n{pro_customer_argument}\n\n"
        f"Decide el veredicto final."
    )
