"""Esquemas de salida estructurada y prompts de los agentes con LLM.

Cada agente devuelve un Pydantic con su contrato (D4). Los prompts mencionan
"JSON" explícitamente porque el endpoint de dev (opencode, compatible con
OpenAI) exige que la palabra aparezca en los mensajes para aceptar
`response_format=json_object`. Es un requisito del proveedor, no del diseño.
"""

from pydantic import BaseModel, Field

from src.enums import DecisionType


class DebateOut(BaseModel):
    """Salida de los dos agentes de debate."""

    argument: str = Field(description="argumento en lenguaje natural, fundamentado en la evidencia")


class ArbiterOut(BaseModel):
    """Salida del Decision Arbiter.

    `confidence` es la confianza **final** (ya ajustada sobre `base_confidence`,
    dentro del delta acotado que aplica el nodo). `rationale` justifica el
    veredicto y, si hubo ajuste de confianza, ese ajuste.
    """

    decision: DecisionType = Field(description="veredicto")
    confidence: float = Field(ge=0.0, le=1.0, description="confianza final 0-1")
    rationale: str = Field(description="justificación del veredicto y del ajuste de confianza")


class ExplainOut(BaseModel):
    """Salida del agente de explicabilidad."""

    explanation_customer: str = Field(description="explicación para el cliente, sin jerga")
    explanation_audit: str = Field(description="explicación de auditoría, trazable a señales y citas")


DEBATE_PRO_FRAUDE_PROMPT = (
    "Eres un analista de fraude. Construye el argumento A FAVOR de sospecha "
    "de fraude para esta transacción, usando SOLO la evidencia provista. "
    "Señala qué señales son las más graves y por qué. No inventes hechos.\n\n"
    "Responde en formato JSON con el campo `argument`.\n\n"
    "Evidencia:\n{evidencia}"
)

DEBATE_PRO_CLIENTE_PROMPT = (
    "Eres un defensor del cliente. Construye el argumento EN DESCARGO de la "
    "transacción, usando SOLO la evidencia provista. Señala qué explicaciones "
    "legítimas podrían justificar cada señal. No inventes hechos.\n\n"
    "Responde en formato JSON con el campo `argument`.\n\n"
    "Evidencia:\n{evidencia}"
)

ARBITER_PROMPT = (
    "Eres el árbitro final de un sistema de detección de fraude. Decide el "
    "veredicto con la evidencia, el debate y las políticas recuperadas.\n\n"
    "Reglas:\n"
    "- El veredicto debe salir de la política más restrictiva que aplique "
    "(BLOCK > ESCALATE_TO_HUMAN > CHALLENGE > APPROVE).\n"
    "- Si la evidencia es contradictoria o insuficiente para un veredicto "
    "autónomo, emite ESCALATE_TO_HUMAN.\n"
    "- La confianza va de 0 a 1: alta cuando la evidencia es clara en un "
    "sentido, baja cuando es contradictoria o falta evidencia.\n"
    "- No cambies la confianza sin justificarlo en `rationale`.\n\n"
    "Responde en formato JSON con los campos `decision`, `confidence` y "
    "`rationale`.\n\n"
    "Evidencia:\n{evidencia}\n\n"
    "Debate pro-fraude:\n{pro_fraud}\n\n"
    "Debate pro-cliente:\n{pro_customer}\n\n"
    "Políticas recuperadas:\n{politicas}"
)

EXPLAIN_PROMPT = (
    "Eres el agente de explicabilidad. Produce dos explicaciones de la "
    "decisión tomada.\n\n"
    "- `explanation_customer`: para el titular de la tarjeta, en lenguaje "
    "claro, sin jerga técnica, explicando qué pasó y qué puede hacer.\n"
    "- `explanation_audit`: para un auditor, trazable: qué señales se "
    "detectaron, qué políticas se citaron y por qué se decidió lo que se "
    "decidió.\n\n"
    "Responde en formato JSON con los campos `explanation_customer` y "
    "`explanation_audit`.\n\n"
    "Veredicto: {decision}\n"
    "Confianza: {confidence}\n\n"
    "Evidencia:\n{evidencia}\n\n"
    "Políticas citadas:\n{politicas}"
)
