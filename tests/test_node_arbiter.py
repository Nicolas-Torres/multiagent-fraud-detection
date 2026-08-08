"""El nodo `decision_arbiter`: el piso determinístico ajustado por juicio LLM.

Sin red: `runtime.context.judge` es un doble. Lo que se prueba acá es el
cableado -que un veredicto por encima del piso se persista tal cual, que
`confidence_rationale` se guarde en cualquier desvío del piso y no sólo
cuando cambia el número de confianza, y que la caída del proveedor degrade a
`ESCALATE_TO_HUMAN` con el piso, no a una excepción. La cuarta guarda que
hace cumplir el piso estructuralmente se prueba en `test_citations.py`.
"""

from dataclasses import dataclass

from multiagent_fraud_detection.arbiter.judge import ArbiterVerdict, FakeJudge
from multiagent_fraud_detection.domain.catalog import Policy, PolicyCatalog, PolicyState
from multiagent_fraud_detection.enums import DecisionType
from multiagent_fraud_detection.graph.nodes import ARBITER, decision_arbiter
from multiagent_fraud_detection.schemas.decision import InternalCitation


def catalogo() -> PolicyCatalog:
    return PolicyCatalog(
        version="2025.1-b1",
        reference_currency="USD",
        policies=(
            Policy(
                "FP-01", "2025.1", "Monto y horario", PolicyState.ACTIVE,
                action=DecisionType.CHALLENGE,
            ),
            Policy(
                "FP-03", "2025.1", "Velocity check", PolicyState.ACTIVE,
                action=DecisionType.BLOCK,
            ),
        ),
    )


def cita(policy_id: str, version: str = "2025.1") -> InternalCitation:
    return InternalCitation(
        policy_id=policy_id, chunk_id=f"{policy_id}:{version}:0", version=version
    )


@dataclass
class FakeRuntime:
    context: object


@dataclass
class FakeGraphContext:
    catalog: object
    judge: object


def estado(**extra):
    base = {
        "policies": ["FP-01"],
        "citations_internal": [cita("FP-01")],
        "base_confidence": 0.4,
        "evidence": [],
        "agent_errors": [],
        "pro_fraud_argument": "argumento de cautela",
        "pro_customer_argument": "argumento de legitimidad",
        "risk_score": 0.4,
    }
    return {**base, **extra}


class JuezRoto:
    def judge(self, system, user):
        raise ConnectionError("proveedor caído")


async def test_veredicto_por_encima_del_piso_se_persiste_tal_cual():
    """FP-01 prescribe CHALLENGE; el Arbiter escala a BLOCK con su propio
    rationale."""
    veredicto = ArbiterVerdict(
        decision=DecisionType.BLOCK,
        confidence=0.8,
        rationale="contradicción expuesta en el debate",
    )
    rt = FakeRuntime(FakeGraphContext(catalogo(), FakeJudge(veredicto)))

    salida = await decision_arbiter(estado(), rt)

    assert salida["decision"] == DecisionType.BLOCK
    assert salida["confidence"] == 0.8
    assert salida["confidence_rationale"] == "contradicción expuesta en el debate"
    assert salida["agent_route"] == [ARBITER]


async def test_veredicto_igual_al_piso_no_deja_rationale():
    veredicto = ArbiterVerdict(
        decision=DecisionType.CHALLENGE, confidence=0.4, rationale="coincide"
    )
    rt = FakeRuntime(FakeGraphContext(catalogo(), FakeJudge(veredicto)))

    salida = await decision_arbiter(estado(), rt)

    assert salida["decision"] == DecisionType.CHALLENGE
    assert "confidence_rationale" not in salida


async def test_escalar_sin_cambiar_la_confianza_igual_deja_rationale():
    """ADR-0016: "cada desvío del piso queda en confidence_rationale" — no
    sólo los que cambian el número de confianza."""
    veredicto = ArbiterVerdict(
        decision=DecisionType.BLOCK,
        confidence=0.4,
        rationale="escala aunque la confianza no cambia",
    )
    rt = FakeRuntime(FakeGraphContext(catalogo(), FakeJudge(veredicto)))

    salida = await decision_arbiter(estado(), rt)

    assert salida["decision"] == DecisionType.BLOCK
    assert salida["confidence"] == 0.4
    assert salida["confidence_rationale"] == "escala aunque la confianza no cambia"


async def test_proveedor_caido_escala_con_el_piso():
    rt = FakeRuntime(FakeGraphContext(catalogo(), JuezRoto()))

    salida = await decision_arbiter(estado(), rt)

    assert salida["decision"] == DecisionType.ESCALATE_TO_HUMAN
    assert salida["confidence"] == 0.4  # base_confidence, el piso de confianza
    assert "proveedor de juicio no disponible" in salida["confidence_rationale"]
    assert salida["agent_errors"][0].agent == ARBITER
    assert salida["agent_errors"][0].error_type == "ConnectionError"


async def test_sin_respaldo_interno_no_llega_a_llamar_al_proveedor():
    """La degradación por evidencia incompleta corre antes: no tiene sentido
    preguntarle al LLM por un piso que no se pudo calcular. Si el nodo
    llamara igual a `JuezRoto`, esta prueba fallaría con `ConnectionError`
    en vez de con la aserción de abajo."""
    rt = FakeRuntime(FakeGraphContext(catalogo(), JuezRoto()))

    salida = await decision_arbiter(
        estado(policies=["FP-03"], citations_internal=[]), rt
    )

    assert salida["decision"] == DecisionType.ESCALATE_TO_HUMAN
    assert "sin respaldo interno" in salida["confidence_rationale"]


async def test_sin_score_deterministico_no_llega_a_llamar_al_proveedor():
    rt = FakeRuntime(FakeGraphContext(catalogo(), JuezRoto()))

    salida = await decision_arbiter(estado(base_confidence=None), rt)

    assert salida["decision"] == DecisionType.ESCALATE_TO_HUMAN
    assert "sin score deterministico" in salida["confidence_rationale"]
