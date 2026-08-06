"""Los prompts de debate: sin control de divulgación —esto no lo lee el
titular, lo lee el Arbiter— pero sí con la misma prohibición de inventar
evidencia que ya usa `explain/customer.py`.
"""

from multiagent_fraud_detection.debate import pro_customer, pro_fraud
from multiagent_fraud_detection.enums import Severity
from multiagent_fraud_detection.graph.state import WorkingSignal


def señal(code="DEVICE_VELOCITY", severity=Severity.MEDIUM):
    return WorkingSignal(
        code=code,
        description=f"detalle de {code}",
        severity=severity,
        emitted_by="behavioral_pattern",
    )


class TestProFraud:
    def test_el_system_prompt_prohibe_inventar(self):
        minuscula = pro_fraud.SYSTEM_PROMPT.lower()
        assert "nunca inventes" in minuscula

    def test_el_system_prompt_no_le_pide_un_veredicto(self):
        minuscula = pro_fraud.SYSTEM_PROMPT.lower()
        assert "no emitas un veredicto" in minuscula

    def test_el_prompt_incluye_la_evidencia_entregada(self):
        prompt = pro_fraud.build_prompt([señal()], ["FP-03"], 0.6)
        assert "DEVICE_VELOCITY" in prompt
        assert "FP-03" in prompt
        assert "0.60" in prompt

    def test_sin_evidencia_no_inventa_contenido(self):
        prompt = pro_fraud.build_prompt([], [], 0.0)
        assert "sin señales" in prompt.lower()
        assert "ninguna política" in prompt.lower()

    def test_hay_respaldo_declarado_y_no_se_disfraza_de_argumento_real(self):
        texto = pro_fraud.fallback_argument()
        assert texto
        assert "no fue posible" in texto.lower()


class TestProCustomer:
    def test_el_system_prompt_prohibe_inventar(self):
        minuscula = pro_customer.SYSTEM_PROMPT.lower()
        assert "nunca inventes" in minuscula

    def test_el_system_prompt_no_permite_negar_una_señal(self):
        minuscula = pro_customer.SYSTEM_PROMPT.lower()
        assert "no niegues una señal" in minuscula

    def test_el_prompt_incluye_la_misma_evidencia(self):
        prompt = pro_customer.build_prompt([señal()], ["FP-03"], 0.6)
        assert "DEVICE_VELOCITY" in prompt
        assert "FP-03" in prompt

    def test_hay_respaldo_declarado_y_no_se_disfraza_de_argumento_real(self):
        texto = pro_customer.fallback_argument()
        assert texto
        assert "no fue posible" in texto.lower()


def test_las_dos_versiones_de_prompt_son_distintas():
    """Son dos roles, dos prompts: si compartieran versión, cambiar uno
    haría mentir a la versión del otro."""
    assert pro_fraud.PROMPT_VERSION != pro_customer.PROMPT_VERSION


def test_los_dos_respaldos_son_distinguibles_entre_si():
    assert pro_fraud.fallback_argument() != pro_customer.fallback_argument()
