"""Cada salida de un LLM que se guarda lleva su versión (ADR-0033).

El árbitro y cada postura del debate sellan su `PROMPT_VERSION` sólo cuando el
LLM respondió. Ausente significa que ningún modelo produjo esa salida: el árbitro
degradó, o el argumento salió del respaldo.
"""

from dataclasses import dataclass

from multiagent_fraud_detection.arbiter import prompt as arbiter_prompt
from multiagent_fraud_detection.arbiter.judge import ArbiterVerdict
from multiagent_fraud_detection.debate import pro_customer, pro_fraud
from multiagent_fraud_detection.domain.catalog import PolicyCatalog
from multiagent_fraud_detection.enums import DecisionType
from multiagent_fraud_detection.graph.nodes import (
    debate_pro_customer,
    debate_pro_fraud,
    decision_arbiter,
)


@dataclass
class _Contexto:
    narrator: object = None
    judge: object = None
    catalog: object = None


@dataclass
class _Runtime:
    context: object


class _Narrador:
    def narrate(self, system, user, *, model, max_tokens, thinking):
        return "un argumento"


class _NarradorRoto:
    def narrate(self, system, user, *, model, max_tokens, thinking):
        raise ConnectionError("proveedor caído")


class _Juez:
    def judge(self, system, user):
        return ArbiterVerdict(decision=DecisionType.APPROVE, confidence=0.9, rationale="ok")


class _JuezRoto:
    def judge(self, system, user):
        raise ConnectionError("proveedor caído")


def _catalogo() -> PolicyCatalog:
    return PolicyCatalog(version="2025.1-b1", reference_currency="USD", policies=())


def _estado_arbitro(**extra) -> dict:
    return {
        "policies": [],
        "citations_internal": [],
        "base_confidence": 0.9,
        "evidence": [],
        "agent_errors": [],
        "pro_fraud_argument": "a",
        "pro_customer_argument": "b",
        "risk_score": 0.0,
        **extra,
    }


async def test_cada_postura_sella_su_version_cuando_el_llm_responde():
    for nodo, modulo, clave in (
        (debate_pro_fraud, pro_fraud, "debate_pro_fraud_prompt_version"),
        (debate_pro_customer, pro_customer, "debate_pro_customer_prompt_version"),
    ):
        salida = await nodo({}, _Runtime(_Contexto(narrator=_Narrador())))
        assert salida[clave] == modulo.PROMPT_VERSION


async def test_un_argumento_de_respaldo_no_lleva_version():
    for nodo, clave in (
        (debate_pro_fraud, "debate_pro_fraud_prompt_version"),
        (debate_pro_customer, "debate_pro_customer_prompt_version"),
    ):
        salida = await nodo({}, _Runtime(_Contexto(narrator=_NarradorRoto())))
        assert "agent_errors" in salida
        assert clave not in salida


async def test_el_arbitro_sella_su_version_cuando_el_llm_responde():
    salida = await decision_arbiter(_estado_arbitro(), _Runtime(_Contexto(judge=_Juez(), catalog=_catalogo())))
    assert salida["arbiter_prompt_version"] == arbiter_prompt.PROMPT_VERSION


async def test_un_arbitro_degradado_no_lleva_version():
    rt_roto = _Runtime(_Contexto(judge=_JuezRoto(), catalog=_catalogo()))
    caido = await decision_arbiter(_estado_arbitro(), rt_roto)
    sin_score = await decision_arbiter(_estado_arbitro(base_confidence=None), rt_roto)

    assert caido["decision"] is DecisionType.ESCALATE_TO_HUMAN
    assert "arbiter_prompt_version" not in caido
    assert "arbiter_prompt_version" not in sin_score


def test_la_api_expone_los_tres_sellos():
    from multiagent_fraud_detection.schemas.decision import DecisionRead

    for campo in ("arbiter_prompt_version", "debate_pro_fraud_prompt_version", "debate_pro_customer_prompt_version"):
        assert campo in DecisionRead.model_fields
