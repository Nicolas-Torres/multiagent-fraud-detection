"""Con un agente de señales caído, el piso nunca es APPROVE (ADR-0032).

Antes, con la misma evidencia (ninguna señal, ninguna política, un agente caído)
el árbitro aprobaba en un caso y pedía verificación en otro, según cómo quedara
redactado el debate. La regla lo saca del LLM. La guarda y el árbitro calculan el
piso con la misma función: si difirieran, la guarda podría rechazar lo que el
árbitro decidió.
"""

from dataclasses import dataclass

import pytest

from multiagent_fraud_detection.arbiter.judge import ArbiterVerdict
from multiagent_fraud_detection.domain.catalog import Policy, PolicyCatalog, PolicyState
from multiagent_fraud_detection.domain.engine import AGENTES_DE_SENALES, piso_efectivo
from multiagent_fraud_detection.enums import DecisionType
from multiagent_fraud_detection.explain.audit import build_audit_explanation
from multiagent_fraud_detection.graph import nodes
from multiagent_fraud_detection.graph.state import AgentError

A, C, E, B = (DecisionType.APPROVE, DecisionType.CHALLENGE, DecisionType.ESCALATE_TO_HUMAN, DecisionType.BLOCK)


def catalogo() -> PolicyCatalog:
    return PolicyCatalog(
        version="2025.1-b1",
        reference_currency="USD",
        policies=(
            Policy("FP-01", "2025.1", "Monto y horario", PolicyState.ACTIVE, action=C),
            Policy("FP-02", "2025.1", "País y dispositivo", PolicyState.ACTIVE, action=E),
            Policy("FP-03", "2025.1", "Velocity", PolicyState.ACTIVE, action=B),
        ),
    )


def test_los_agentes_de_senales_son_los_nodos_de_evidencia_menos_el_rag():
    assert {nodes.CONTEXT, nodes.BEHAVIORAL, nodes.THREAT_INTEL} == AGENTES_DE_SENALES
    assert nodes.POLICY_RAG not in AGENTES_DE_SENALES


@pytest.mark.parametrize(
    ("politicas", "degradados", "esperado"),
    [
        ((), (), A),
        ((), ("behavioral_pattern",), C),
        ((), ("transaction_context",), C),
        ((), ("external_threat_intel",), C),
        ((), ("internal_policy_rag",), A),  # ADR-0011: el RAG no decide qué aplica
        ((), ("debate_pro_fraud", "decision_arbiter"), A),  # no producen evidencia
        (("FP-01",), ("behavioral_pattern",), C),
        (("FP-02",), ("behavioral_pattern",), E),  # ya era más cauteloso: no cambia
        (("FP-03",), ("behavioral_pattern",), B),
    ],
)
def test_piso_efectivo(politicas, degradados, esperado):
    assert piso_efectivo(catalogo(), politicas, degradados) is esperado


def _error(agente: str) -> AgentError:
    return AgentError(agent=agente, error_type="TimeoutError", message="caído")


def _estado(decision: DecisionType, degradados: list[str]) -> dict:
    return {
        "decision": decision,
        "policies": [],
        "citations_internal": [],
        "base_confidence": 0.7,
        "confidence": 0.7,
        "agent_errors": [_error(a) for a in degradados],
    }


def test_la_guarda_rechaza_aprobar_con_un_agente_de_senales_caido():
    with pytest.raises(ValueError, match="por debajo del piso CHALLENGE"):
        nodes._verificar_invariantes(_estado(A, ["behavioral_pattern"]), catalogo())


def test_la_guarda_acepta_challenge_con_un_agente_de_senales_caido():
    nodes._verificar_invariantes(_estado(C, ["behavioral_pattern"]), catalogo())


def test_la_guarda_acepta_aprobar_con_el_rag_caido():
    nodes._verificar_invariantes(_estado(A, ["internal_policy_rag"]), catalogo())


@dataclass
class _Contexto:
    catalog: object
    judge: object


@dataclass
class _Runtime:
    context: object


class _JuezEspia:
    def __init__(self):
        self.user = ""

    def judge(self, system, user):
        self.user = user
        return ArbiterVerdict(decision=C, confidence=0.7, rationale="verificar")


async def test_el_arbitro_recibe_el_piso_efectivo():
    espia = _JuezEspia()
    estado = {
        "policies": [],
        "citations_internal": [],
        "base_confidence": 0.7,
        "evidence": [],
        "agent_errors": [_error("behavioral_pattern")],
        "pro_fraud_argument": "a",
        "pro_customer_argument": "b",
        "risk_score": 0.0,
    }

    await nodes.decision_arbiter(estado, _Runtime(_Contexto(catalogo(), espia)))

    assert "Piso determinista (cota mínima de cautela): CHALLENGE" in espia.user


def test_la_auditoria_dice_por_que_el_piso_no_es_approve():
    texto = build_audit_explanation(
        {
            "decision": C,
            "policies": [],
            "citations_internal": [],
            "signals": [],
            "agent_route": [],
            "agent_errors": [_error("behavioral_pattern")],
            "confidence": 0.7,
        }
    )
    assert "el piso no puede ser APPROVE" in texto


def test_la_auditoria_no_lo_dice_si_solo_cayo_el_rag():
    texto = build_audit_explanation(
        {
            "decision": A,
            "policies": [],
            "citations_internal": [],
            "signals": [],
            "agent_route": [],
            "agent_errors": [_error("internal_policy_rag")],
            "confidence": 0.7,
        }
    )
    assert "el piso no puede ser APPROVE" not in texto
