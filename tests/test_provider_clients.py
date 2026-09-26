"""Los adaptadores de proveedor crean **un solo** cliente aunque varios hilos
lo pidan a la vez en frío (incidente 0007).

El grafo comparte cada adaptador entre análisis concurrentes y lo llama desde
`asyncio.to_thread`. Sin lock, cada hilo crea su cliente, el último pisa a los
demás y el recolector cierra los huérfanos con un request todavía en vuelo.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import anthropic
import pytest
from google import genai
from langsmith import wrappers

from multiagent_fraud_detection.arbiter.judge import AnthropicJudge
from multiagent_fraud_detection.explain.narrator import AnthropicNarrator
from multiagent_fraud_detection.intel.searcher import AnthropicSearcher
from multiagent_fraud_detection.retrieval.embeddings import GeminiEmbedder

HILOS = 8


class _ClienteLento:
    """Constructor lento: abre la ventana en la que otro hilo puede ver
    `_client is None` y crear el suyo."""

    creados = 0
    _cuenta = threading.Lock()

    def __init__(self, *args: object, **kwargs: object) -> None:
        time.sleep(0.05)
        with _ClienteLento._cuenta:
            _ClienteLento.creados += 1


@pytest.mark.parametrize(
    ("adaptador", "modulo", "nombre"),
    [
        (GeminiEmbedder, genai, "Client"),
        (AnthropicJudge, anthropic, "Anthropic"),
        (AnthropicNarrator, anthropic, "Anthropic"),
        (AnthropicSearcher, anthropic, "Anthropic"),
    ],
)
def test_varios_hilos_en_frio_crean_un_solo_cliente(
    monkeypatch, adaptador, modulo, nombre
):
    monkeypatch.setattr(modulo, nombre, _ClienteLento)
    monkeypatch.setattr(wrappers, "wrap_anthropic", lambda cliente: cliente)
    monkeypatch.setattr(_ClienteLento, "creados", 0)
    instancia = adaptador(api_key="clave-de-prueba")
    todos_listos = threading.Barrier(HILOS)

    def pedir():
        todos_listos.wait()
        return instancia._cliente()

    with ThreadPoolExecutor(HILOS) as ex:
        clientes = list(ex.map(lambda _: pedir(), range(HILOS)))

    assert _ClienteLento.creados == 1
    assert all(c is clientes[0] for c in clientes)
