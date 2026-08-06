"""El puerto `Searcher`: extracción defensiva y parseo estricto de fecha.

Ninguna de estas pruebas toca red. `AnthropicSearcher._cliente()` se prueba
sólo hasta el punto donde levantaría la llamada real.
"""

from datetime import date
from types import SimpleNamespace

import pytest

from multiagent_fraud_detection.config.settings import settings
from multiagent_fraud_detection.intel.searcher import (
    AnthropicSearcher,
    FakeSearcher,
    SearchError,
    SearchResult,
    _extraer,
    parse_page_age,
)


def _bloque_resultado(*items: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(type="web_search_tool_result", content=list(items))


def _item(url="https://asbanc.com.pe/a", title="Alerta", page_age="April 30, 2025"):
    return SimpleNamespace(url=url, title=title, page_age=page_age)


class TestParsePageAge:
    def test_formato_documentado(self):
        assert parse_page_age("April 30, 2025") == date(2025, 4, 30)

    def test_tolera_espacios(self):
        assert parse_page_age("  April 30, 2025  ") == date(2025, 4, 30)

    def test_none_da_none(self):
        assert parse_page_age(None) is None

    def test_vacio_da_none(self):
        assert parse_page_age("") is None

    @pytest.mark.parametrize(
        "valor",
        [
            "3 days ago",  # relativo, no fecha
            "2025-04-30",  # ISO, no el formato documentado
            "30 de abril de 2025",  # otro idioma
            "April 2025",  # sin día
        ],
    )
    def test_formato_no_documentado_rechaza(self, valor):
        assert parse_page_age(valor) is None


class TestExtraer:
    def test_sin_contenido_da_vacio(self):
        assert _extraer(SimpleNamespace(content=[])) == ()

    def test_ignora_texto_del_modelo(self):
        respuesta = SimpleNamespace(
            content=[SimpleNamespace(type="text", text="cualquier URL que invente")]
        )
        assert _extraer(respuesta) == ()

    def test_extrae_url_titulo_y_page_age_del_bloque_de_resultado(self):
        respuesta = SimpleNamespace(
            content=[
                _bloque_resultado(
                    _item(
                        url="https://sbs.gob.pe/alertas/x",
                        title="SBS - Alerta de fraude",
                        page_age="April 30, 2025",
                    )
                )
            ]
        )

        assert _extraer(respuesta) == (
            SearchResult(
                url="https://sbs.gob.pe/alertas/x",
                title="SBS - Alerta de fraude",
                page_age="April 30, 2025",
            ),
        )

    def test_bloque_de_error_no_es_lista_y_no_rompe(self):
        # `web_search_tool_result_error`: mismo `type`, `content` es un objeto.
        respuesta = SimpleNamespace(
            content=[
                SimpleNamespace(
                    type="web_search_tool_result",
                    content=SimpleNamespace(
                        type="web_search_tool_result_error",
                        error_code="max_uses_exceeded",
                    ),
                )
            ]
        )
        assert _extraer(respuesta) == ()

    def test_item_sin_url_se_descarta(self):
        respuesta = SimpleNamespace(content=[_bloque_resultado(_item(url=None))])
        assert _extraer(respuesta) == ()

    def test_item_sin_titulo_se_descarta(self):
        respuesta = SimpleNamespace(content=[_bloque_resultado(_item(title=None))])
        assert _extraer(respuesta) == ()

    def test_item_sin_page_age_da_none(self):
        item = SimpleNamespace(url="https://asbanc.com.pe/a", title="Alerta")
        respuesta = SimpleNamespace(content=[_bloque_resultado(item)])

        [resultado] = _extraer(respuesta)
        assert resultado.page_age is None

    def test_bloque_desconocido_se_saltea(self):
        respuesta = SimpleNamespace(
            content=[
                SimpleNamespace(type="server_tool_use", input={"query": "x"}),
                _bloque_resultado(_item()),
            ]
        )
        assert len(_extraer(respuesta)) == 1


class TestFakeSearcher:
    def test_devuelve_los_resultados_configurados_sin_mirar_los_argumentos(self):
        resultados = (
            SearchResult(url="https://asbanc.com.pe/a", title="A", page_age=None),
        )
        buscador = FakeSearcher(results=resultados)

        assert buscador.search("query", frozenset({"asbanc.com.pe"})) == resultados
        assert buscador.search("otra query", frozenset()) == resultados


class TestAnthropicSearcher:
    def test_sin_clave_levanta_search_error(self, monkeypatch):
        monkeypatch.setattr(settings, "anthropic_api_key", None)
        buscador = AnthropicSearcher(api_key=None)

        with pytest.raises(SearchError, match="ANTHROPIC_API_KEY"):
            buscador.search("query", frozenset({"asbanc.com.pe"}))
