"""Una respuesta que no terminó no se usa como si estuviera completa (ADR-0031).

Sonnet 5 razona por defecto, y ese razonamiento cuenta dentro de `max_tokens`.
Con el tope anterior del árbitro (500), un caso difícil cortaba el JSON del
veredicto; un texto del narrador cortado se habría guardado a medias. Además,
el modo de razonamiento viaja explícito: si el proveedor cambia su default, no
cambia lo que corre.
"""

import json
from types import SimpleNamespace

import pytest

from multiagent_fraud_detection.arbiter import prompt as arbiter
from multiagent_fraud_detection.arbiter.judge import AnthropicJudge, JudgeError
from multiagent_fraud_detection.debate import pro_customer, pro_fraud
from multiagent_fraud_detection.explain import customer
from multiagent_fraud_detection.explain.narrator import (
    AnthropicNarrator,
    NarrationError,
)

VEREDICTO = json.dumps({"decision": "CHALLENGE", "confidence": 0.6, "rationale": "falta verificar"})


class _Mensajes:
    def __init__(self, stop_reason: str, texto: str):
        self.stop_reason = stop_reason
        self.texto = texto
        self.kwargs: dict = {}

    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            stop_reason=self.stop_reason,
            content=[
                SimpleNamespace(type="thinking", thinking="…"),
                SimpleNamespace(type="text", text=self.texto),
            ],
        )


def _juez(stop_reason: str, texto: str = VEREDICTO) -> tuple[AnthropicJudge, _Mensajes]:
    mensajes = _Mensajes(stop_reason, texto)
    juez = AnthropicJudge(api_key="clave-de-prueba")
    juez._client = SimpleNamespace(messages=mensajes)
    return juez, mensajes


def _narrador(stop_reason: str, texto: str = "un argumento") -> tuple[AnthropicNarrator, _Mensajes]:
    mensajes = _Mensajes(stop_reason, texto)
    narrador = AnthropicNarrator(api_key="clave-de-prueba")
    narrador._client = SimpleNamespace(messages=mensajes)
    return narrador, mensajes


def test_el_arbitro_pide_su_razonamiento_tope_y_esquema():
    juez, mensajes = _juez("end_turn")

    veredicto = juez.judge("system", "estado")

    assert veredicto.decision.value == "CHALLENGE"
    k = mensajes.kwargs
    assert k["model"] == arbiter.MODEL
    assert k["max_tokens"] == arbiter.MAX_TOKENS
    assert k["thinking"] == {"type": arbiter.THINKING}
    assert k["output_config"]["format"]["type"] == "json_schema"


@pytest.mark.parametrize("stop_reason", ["max_tokens", "refusal"])
def test_un_veredicto_que_no_termino_es_un_error_con_su_causa(stop_reason):
    # El JSON cortado de verdad: lo que devolvía el proveedor con el tope viejo.
    juez, _ = _juez(stop_reason, texto='{"decision":"CHALLENGE","confidence":0.6,"rationale":"el piso no')

    with pytest.raises(JudgeError, match=f"stop_reason={stop_reason}"):
        juez.judge("system", "estado")


def test_un_veredicto_terminado_pero_invalido_es_un_error():
    juez, _ = _juez("end_turn", texto='{"decision":"QUIZAS"}')

    with pytest.raises(JudgeError, match="estructurado válido"):
        juez.judge("system", "estado")


@pytest.mark.parametrize("stop_reason", ["max_tokens", "refusal"])
def test_un_texto_que_no_termino_no_se_devuelve(stop_reason):
    narrador, _ = _narrador(stop_reason, texto="El patrón es compatible con una toma de")

    with pytest.raises(NarrationError, match=f"stop_reason={stop_reason}"):
        narrador.narrate("system", "user", model="m", max_tokens=10, thinking="disabled")


def test_el_narrador_envia_el_razonamiento_que_recibe():
    narrador, mensajes = _narrador("end_turn")

    assert narrador.narrate("s", "u", model="m", max_tokens=10, thinking="disabled") == "un argumento"
    assert mensajes.kwargs["thinking"] == {"type": "disabled"}


@pytest.mark.parametrize("modulo", [arbiter, pro_fraud, pro_customer, customer])
def test_cada_llamada_declara_un_modo_de_razonamiento_valido(modulo):
    """Los dos modos que acepta `claude-sonnet-5`. Sonnet 5.5 no acepta
    `disabled` (usa `between_tools`): si cambia el modelo, este test obliga a
    revisar el modo (ADR-0031)."""
    assert modulo.MODEL == "claude-sonnet-5"
    assert modulo.THINKING in {"adaptive", "disabled"}
