"""El guard de operaciones destructivas.

`seed.py --reset` ejecuta `TRUNCATE ... CASCADE` y arrastra `cases`, `decisions`,
`signals` y `human_resolutions` — la evidencia del entregable 8. El guard existe
para que eso no dependa de que nadie escriba la bandera equivocada (ADR-0010).

Lo que estos tests protegen no es el caso feliz sino **la dirección de la
lista**: prohibir por lista negra parece equivalente y falla abierto.
"""

import pytest

from multiagent_fraud_detection.config.settings import Settings

URL = "postgresql+psycopg://x:x@localhost:5432/x"


@pytest.fixture(autouse=True)
def _ambiente_limpio(monkeypatch):
    """Aísla los tests de la configuración de quien los corre.

    `Settings` lee de dos fuentes que acá estorban: el `.env` del repo y las
    variables del shell. Las dos harían que el resultado dependa de la máquina
    —y la variable bajo prueba es justamente esa—.

    Es la misma trampa que ya apareció en `conftest.py`: un test que consulta el
    ambiente en vez de fijarlo no prueba el código, prueba la configuración.
    """
    monkeypatch.delenv("ENVIRONMENT", raising=False)


def ajustes(environment=None) -> Settings:
    """Construye `Settings` ignorando el `.env`.

    `_env_file=None` es lo que apaga la lectura del archivo. Sin eso,
    `ENVIRONMENT=local` en el `.env` de desarrollo haría pasar el test que
    verifica el caso "variable ausente" —midiendo la máquina, no el default—.
    """
    campos = {"database_url": URL, "_env_file": None}
    if environment is not None:
        campos["environment"] = environment
    return Settings(**campos)


def test_local_permite_destruir():
    assert ajustes("local").permite_operaciones_destructivas


@pytest.mark.parametrize("entorno", ["production", "staging", "prod", "qa", "demo", "uat"])
def test_ningun_otro_ambiente_conocido_lo_permite(entorno):
    """Una lista negra habría dejado pasar `prod`, `qa`, `demo` y `uat`.

    Son los nombres que aparecen cuando alguien crea un ambiente nuevo y no
    revisa el guard — el escenario exacto contra el que se invirtió la lista.
    """
    assert not ajustes(entorno).permite_operaciones_destructivas


def test_la_variable_ausente_rechaza():
    """El caso que decide el diseño.

    Con lista negra, `ENVIRONMENT` sin setear pasaría el filtro y `--reset`
    procedería. Es además el estado por defecto de cualquier `.env` que no se
    haya actualizado, así que sería el escenario más frecuente, no el raro.
    """
    assert not ajustes().permite_operaciones_destructivas
    assert ajustes().environment == "unknown"


def test_la_comparacion_es_exacta():
    """`LOCAL`, `local `, `localhost` y `local-dev` no son `local`.

    Normalizar acá sería conveniente y equivocado: un guard que interpreta lo
    que quisiste decir es un guard que a veces interpreta de más.
    """
    for casi in ["LOCAL", "Local", "local ", "localhost", "local-dev", ""]:
        assert not ajustes(casi).permite_operaciones_destructivas


def test_el_default_no_es_local():
    """Si alguien "simplifica" el default a `local`, este test lo frena.

    Sería el cambio de una palabra y convertiría el olvido de configurar en
    autorización para borrar la base.
    """
    assert Settings.model_fields["environment"].default != "local"
