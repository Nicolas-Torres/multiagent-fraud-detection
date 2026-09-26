"""Cada llamada a un LLM usa el modelo que declara su sello (ADR-0026).

Hasta ADR-0026 el debate llamaba al narrador compartido sin modelo ni tope, y
corría con los de la explicación mientras su `PROMPT_VERSION` decía otra cosa.
Estos tests atan el modelo que **viaja** en la llamada al que **se sella**.
"""

from dataclasses import dataclass
from types import SimpleNamespace

from multiagent_fraud_detection.debate import pro_customer, pro_fraud
from multiagent_fraud_detection.enums import DecisionType
from multiagent_fraud_detection.explain import customer
from multiagent_fraud_detection.graph.nodes import (
    debate_pro_customer,
    debate_pro_fraud,
    explainability,
)
from multiagent_fraud_detection.intel import searcher, snapshot


class NarradorEspia:
    def __init__(self):
        self.llamadas: list[tuple[str, int]] = []

    def narrate(self, system, user, *, model, max_tokens):
        self.llamadas.append((model, max_tokens))
        return "[texto]"


@dataclass
class _Contexto:
    narrator: object


@dataclass
class _Runtime:
    context: object


def _modelo_sellado(prompt_version: str) -> str:
    return prompt_version.split(":", 1)[0]


async def _llamada_de(nodo, estado):
    espia = NarradorEspia()
    salida = await nodo(estado, _Runtime(_Contexto(espia)))
    assert "agent_errors" not in salida
    [llamada] = espia.llamadas
    return llamada


async def test_el_debate_usa_su_propio_modelo_y_tope():
    for nodo, modulo in (
        (debate_pro_fraud, pro_fraud),
        (debate_pro_customer, pro_customer),
    ):
        modelo, tope = await _llamada_de(nodo, {})
        assert (modelo, tope) == (modulo.MODEL, modulo.MAX_TOKENS)
        assert modelo == _modelo_sellado(modulo.PROMPT_VERSION)


async def test_la_explicacion_usa_su_propio_modelo_y_tope():
    modelo, tope = await _llamada_de(
        explainability, {"decision": DecisionType.APPROVE, "signals": []}
    )
    assert (modelo, tope) == (customer.MODEL, customer.MAX_TOKENS)
    assert modelo == _modelo_sellado(customer.PROMPT_VERSION)


def test_explicacion_y_debate_no_comparten_modelo_por_accidente():
    """La explicación está en Haiku y el debate en Sonnet (ADR-0026). Si
    alguien los iguala, que sea a propósito y actualizando este test."""
    assert customer.MODEL != pro_fraud.MODEL


class _MensajesFalsos:
    def __init__(self):
        self.kwargs: dict = {}

    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(content=[])


def test_la_busqueda_pide_una_sola_busqueda_sin_prosa_y_con_el_modelo_sellado():
    mensajes = _MensajesFalsos()
    buscador = searcher.AnthropicSearcher(api_key="clave-de-prueba")
    buscador._client = SimpleNamespace(messages=mensajes)

    buscador.search("consulta", frozenset({"sbs.gob.pe"}))

    k = mensajes.kwargs
    assert k["model"] == snapshot.MODEL == _modelo_sellado(snapshot.SNAPSHOT_VERSION)
    assert k["system"] == snapshot.SYSTEM_PROMPT
    assert k["max_tokens"] == searcher.MAX_TOKENS <= 100
    assert k["tools"][0]["max_uses"] == 1
