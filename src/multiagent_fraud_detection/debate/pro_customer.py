"""`pro_customer_argument`: el caso a favor de tratar la operación como legítima.

Molde simétrico a [`pro_fraud`](pro_fraud.py) — mismas reglas, mismos insumos,
argumento contrario. Ver ese módulo para el porqué del rol, la ausencia de
control de divulgación y el versionado del prompt; acá sólo lo que cambia.
"""

from __future__ import annotations

from collections.abc import Sequence

from multiagent_fraud_detection.graph.state import WorkingSignal

MODEL = "claude-sonnet-5"
TEMPLATE_TAG = "debate-pro-customer"
GENERATION = 1

PROMPT_VERSION = f"{MODEL}:{TEMPLATE_TAG}:{GENERATION}"

MAX_TOKENS = 300

SYSTEM_PROMPT = """\
Eres el analista que argumenta a favor de tratar una operación como
legítima, dentro de un sistema antifraude. Tu argumento lo lee otro
componente automatizado, nunca el titular de la tarjeta.

Reglas que no puedes romper:

1. Usa ÚNICAMENTE la evidencia que se te entrega: señales, políticas
   disparadas y el puntaje de riesgo. NUNCA inventes hechos, historial ni
   intención del titular que no estén en esa evidencia.
2. Argumenta desde los límites de la evidencia en contra: señales aisladas
   que ninguna política reúne, ausencia de corroboración, puntaje de riesgo
   bajo. No niegues una señal que sí ocurrió.
3. No emitas un veredicto ni recomiendes una acción (bloquear, aprobar,
   escalar, desafiar): eso lo decide otro componente. Tu único trabajo es
   argumentar con la evidencia disponible.
4. Entre dos y cuatro oraciones, en español neutro.
5. Devuelve solo el argumento, sin encabezados, comillas ni comentarios.
"""


def build_prompt(
    evidence: Sequence[WorkingSignal], policies: Sequence[str], risk_score: float
) -> str:
    """El mensaje de usuario: la misma evidencia que ve `pro_fraud`, sin
    resolver nada por él — el debate sólo funciona si los dos argumentan
    sobre el mismo caso."""
    señales = (
        "\n".join(
            f"- {s.code} ({s.severity.value}): {s.description}" for s in evidence
        )
        if evidence
        else "(sin señales)"
    )
    politicas = ", ".join(policies) if policies else "(ninguna política disparó)"
    return (
        f"Señales detectadas:\n{señales}\n\n"
        f"Políticas que dispararon: {politicas}\n"
        f"Puntaje de riesgo determinístico: {risk_score:.2f}\n\n"
        f"Argumenta por qué esta operación puede tratarse como legítima."
    )


def fallback_argument() -> str:
    """No es un mensaje de error: el Arbiter no tiene por qué enterarse de que
    el proveedor se cayó, pero sí tiene que saber que esto no es un argumento
    real y no debe pesar como tal."""
    return (
        "No fue posible generar el argumento a favor de la legitimidad: el "
        "proveedor de juicio no respondió."
    )
