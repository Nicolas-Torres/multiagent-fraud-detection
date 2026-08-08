"""El puerto `Judge`: veredicto estructurado del Arbiter, y el prompt que lo
arma. Sin red: `AnthropicJudge._cliente()` se prueba sólo hasta el punto
donde levantaría la llamada real, mismo criterio que `test_searcher.py`.
"""

import pytest
from pydantic import ValidationError

from multiagent_fraud_detection.arbiter import prompt as arbiter_prompt
from multiagent_fraud_detection.arbiter.judge import (
    AnthropicJudge,
    ArbiterVerdict,
    FakeJudge,
    JudgeError,
)
from multiagent_fraud_detection.config.settings import settings
from multiagent_fraud_detection.enums import DecisionType, Severity
from multiagent_fraud_detection.graph.state import WorkingSignal


def señal(code="DEVICE_VELOCITY"):
    return WorkingSignal(
        code=code,
        description=f"detalle de {code}",
        severity=Severity.MEDIUM,
        emitted_by="behavioral_pattern",
    )


class TestArbiterVerdict:
    def test_confianza_fuera_de_rango_rechaza(self):
        with pytest.raises(ValidationError):
            ArbiterVerdict(
                decision=DecisionType.APPROVE, confidence=1.5, rationale="x"
            )

    def test_rationale_vacio_rechaza(self):
        with pytest.raises(ValidationError):
            ArbiterVerdict(decision=DecisionType.APPROVE, confidence=0.5, rationale="")

    def test_decision_invalida_rechaza(self):
        with pytest.raises(ValidationError):
            ArbiterVerdict(decision="no-existe", confidence=0.5, rationale="x")


class TestFakeJudge:
    def test_devuelve_el_veredicto_configurado_sin_mirar_los_argumentos(self):
        veredicto = ArbiterVerdict(
            decision=DecisionType.BLOCK, confidence=0.9, rationale="test"
        )
        juez = FakeJudge(verdict=veredicto)

        assert juez.judge("s", "u") == veredicto
        assert juez.judge("otro", "otro") == veredicto

    def test_no_se_disfraza_de_real(self):
        assert FakeJudge().judge("s", "u").rationale == "[veredicto de prueba]"


class TestAnthropicJudge:
    def test_sin_clave_levanta_judge_error(self, monkeypatch):
        monkeypatch.setattr(settings, "anthropic_api_key", None)
        juez = AnthropicJudge(api_key=None)

        with pytest.raises(JudgeError, match="ANTHROPIC_API_KEY"):
            juez.judge("s", "u")


class TestPrompt:
    def test_el_system_prompt_declara_la_regla_del_piso(self):
        minuscula = arbiter_prompt.SYSTEM_PROMPT.lower()
        assert "nunca" in minuscula
        assert "block > escalate_to_human > challenge > approve" in minuscula

    def test_el_prompt_incluye_el_piso_y_la_evidencia(self):
        texto = arbiter_prompt.build_prompt(
            floor=DecisionType.CHALLENGE,
            evidence=[señal()],
            policies=["FP-03"],
            pro_fraud_argument="a favor de la cautela",
            pro_customer_argument="a favor de la legitimidad",
            degraded_agents=["internal_policy_rag"],
            risk_score=0.6,
            base_confidence=0.4,
        )
        assert "CHALLENGE" in texto
        assert "DEVICE_VELOCITY" in texto
        assert "FP-03" in texto
        assert "a favor de la cautela" in texto
        assert "a favor de la legitimidad" in texto
        assert "internal_policy_rag" in texto

    def test_sin_evidencia_ni_degradados_no_inventa_contenido(self):
        texto = arbiter_prompt.build_prompt(
            floor=DecisionType.APPROVE,
            evidence=[],
            policies=[],
            pro_fraud_argument="x",
            pro_customer_argument="y",
            degraded_agents=[],
            risk_score=0.0,
            base_confidence=0.5,
        )
        assert "sin señales" in texto.lower()
        assert "ninguna política" in texto.lower()
        assert "(ninguno)" in texto
