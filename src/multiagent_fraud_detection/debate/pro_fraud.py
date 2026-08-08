"""`pro_fraud_argument`: el caso a favor de tratar la operación como sospechosa.

## El rol en el debate

Es una de las dos voces que el Arbiter LLM escucha antes de fallar (ADR-0006,
ADR-0016). No decide nada — no conoce el piso determinista
(`prescribed_action`), y no puede citar un `policy_id` como si lo autorizara.
Su trabajo es más angosto: argumentar, con la evidencia del caso y nada más,
por qué el sistema debería ser cauteloso.

## Lee identificadores, no los otorga

A diferencia de `explain/customer.py`, este texto nunca lo lee el titular —lo
lee el Arbiter y, después, un analista en la auditoría—. Puede nombrar
`policy_id` y códigos de señal como contexto: leerlos no es lo mismo que
generarlos, que es la regla que protege CLAUDE.md. El `SYSTEM_PROMPT` sí
prohíbe inventar evidencia que el caso no tiene, la misma prohibición que ya
usa `explain/customer.py` para no inventar motivos, aplicada acá a una
audiencia distinta.

## El prompt está versionado

Mismo criterio que `explain/customer.py` e `intel/snapshot.py`: el prompt es
un parámetro de derivación. El segmento de modelo de `PROMPT_VERSION` es una
garantía del proveedor —los IDs de Anthropic desde la generación 4.6 son
fijos—; el segmento de generación es responsabilidad nuestra.
"""

from __future__ import annotations

from collections.abc import Sequence

from multiagent_fraud_detection.graph.state import WorkingSignal

MODEL = "claude-sonnet-5"
TEMPLATE_TAG = "debate-pro-fraud"
GENERATION = 1

PROMPT_VERSION = f"{MODEL}:{TEMPLATE_TAG}:{GENERATION}"

MAX_TOKENS = 300

SYSTEM_PROMPT = """\
Eres el analista que argumenta a favor de tratar una operación como
sospechosa, dentro de un sistema antifraude. Tu argumento lo lee otro
componente automatizado, nunca el titular de la tarjeta.

Reglas que no puedes romper:

1. Usa ÚNICAMENTE la evidencia que se te entrega: señales, políticas
   disparadas y el puntaje de riesgo. NUNCA inventes hechos, historial ni
   intención del titular que no estén en esa evidencia.
2. Si la evidencia es débil, dilo: un argumento que exagera una señal aislada
   es menos útil que uno que reconoce sus límites.
3. No emitas un veredicto ni recomiendes una acción (bloquear, aprobar,
   escalar, desafiar): eso lo decide otro componente. Tu único trabajo es
   argumentar con la evidencia disponible.
4. Entre dos y cuatro oraciones, en español neutro.
5. Devuelve solo el argumento, sin encabezados, comillas ni comentarios.
"""


def build_prompt(
    evidence: Sequence[WorkingSignal], policies: Sequence[str], risk_score: float
) -> str:
    """El mensaje de usuario: la evidencia del caso, sin resolver nada por él."""
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
        f"Argumenta por qué esta operación merece cautela."
    )


def fallback_argument() -> str:
    """No es un mensaje de error: el Arbiter no tiene por qué enterarse de que
    el proveedor se cayó, pero sí tiene que saber que esto no es un argumento
    real y no debe pesar como tal."""
    return (
        "No fue posible generar el argumento a favor de la cautela: el "
        "proveedor de juicio no respondió."
    )
