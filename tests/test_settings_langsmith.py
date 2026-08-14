"""`propagar_langsmith`: la traducción de `Settings` a `os.environ`.

LangGraph y `langsmith.wrappers.wrap_anthropic` no leen configuración
inyectada — leen `os.environ` directo, así que este es el único punto que
puede hacerlos mentir sobre si están trazando o no. Mismo criterio que
`test_settings_guard.py`: probar las dos direcciones, no sólo el caso feliz.
"""

import os

import pytest

from multiagent_fraud_detection.config.settings import Settings, propagar_langsmith

URL = "postgresql+psycopg://x:x@localhost:5432/x"
_VARIABLES = ("LANGSMITH_TRACING", "LANGSMITH_API_KEY", "LANGSMITH_PROJECT")


@pytest.fixture(autouse=True)
def _ambiente_langsmith_aislado():
    """Guarda y restaura las tres variables a mano.

    `propagar_langsmith` muta `os.environ` con `setdefault` **directo** —no a
    través de `monkeypatch`—, así que el teardown automático de `monkeypatch`
    no alcanza para deshacerlo. Sin este guardado, un test que prende tracing
    filtraría las variables a todo lo que corra después en el mismo proceso
    de pytest, no sólo a los tests de este archivo.
    """
    originales = {var: os.environ.pop(var, None) for var in _VARIABLES}
    yield
    for var, valor in originales.items():
        if valor is None:
            os.environ.pop(var, None)
        else:
            os.environ[var] = valor


def ajustes(**overrides) -> Settings:
    campos = {"database_url": URL, "_env_file": None, **overrides}
    return Settings(**campos)


def test_tracing_apagado_no_toca_el_ambiente():
    propagar_langsmith(ajustes(langsmith_tracing=False, langsmith_api_key="ls-x"))

    assert "LANGSMITH_TRACING" not in os.environ
    assert "LANGSMITH_API_KEY" not in os.environ


def test_tracing_prendido_sin_clave_no_alcanza():
    """El flag solo no autoriza nada — la clave ausente es la que manda.

    Evita el escenario donde alguien pone `LANGSMITH_TRACING=true` sin clave
    y el sistema intenta trazar hacia una cuenta que no existe.
    """
    propagar_langsmith(ajustes(langsmith_tracing=True, langsmith_api_key=None))

    assert "LANGSMITH_TRACING" not in os.environ
    assert "LANGSMITH_API_KEY" not in os.environ


def test_tracing_prendido_con_clave_propaga_los_tres():
    propagar_langsmith(
        ajustes(
            langsmith_tracing=True,
            langsmith_api_key="ls-x",
            langsmith_project="fraud-detection",
        )
    )

    assert os.environ["LANGSMITH_TRACING"] == "true"
    assert os.environ["LANGSMITH_API_KEY"] == "ls-x"
    assert os.environ["LANGSMITH_PROJECT"] == "fraud-detection"


def test_sin_project_no_lo_setea():
    propagar_langsmith(
        ajustes(langsmith_tracing=True, langsmith_api_key="ls-x", langsmith_project=None)
    )

    assert os.environ["LANGSMITH_TRACING"] == "true"
    assert "LANGSMITH_PROJECT" not in os.environ


def test_no_pisa_un_ambiente_ya_seteado_a_mano():
    """`setdefault`, no asignación: un `os.environ` fijado afuera (CI, por
    ejemplo) tiene que ganarle a lo que `Settings` traiga del `.env`."""
    os.environ["LANGSMITH_PROJECT"] = "otro-proyecto"

    propagar_langsmith(
        ajustes(
            langsmith_tracing=True,
            langsmith_api_key="ls-x",
            langsmith_project="fraud-detection",
        )
    )

    assert os.environ["LANGSMITH_PROJECT"] == "otro-proyecto"
