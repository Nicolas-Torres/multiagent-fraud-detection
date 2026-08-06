"""El allowlist es la única garantía de gobernanza de la etapa, y es pura.

Ninguna de estas pruebas toca red ni base.
"""

import pytest

from multiagent_fraud_detection.intel.governance import (
    enforce,
    is_allowed,
    normalize_allowlist,
)

LISTA = normalize_allowlist(["asbanc.com.pe", "SBS.gob.pe", "krebsonsecurity.com."])


def test_normaliza_a_minuscula_y_sin_punto_final():
    assert LISTA == {"asbanc.com.pe", "sbs.gob.pe", "krebsonsecurity.com"}


@pytest.mark.parametrize(
    "url",
    [
        "https://asbanc.com.pe/alertas",
        "https://www.asbanc.com.pe/alertas",           # subdominio: entra
        "https://boletin.prensa.sbs.gob.pe/x",         # subdominio anidado
        "https://ASBANC.com.pe/A",                     # host case-insensitive
    ],
)
def test_acepta_dominio_y_subdominios(url):
    assert is_allowed(url, LISTA)


@pytest.mark.parametrize(
    ("url", "por_que"),
    [
        ("http://asbanc.com.pe/x", "esquema no https"),
        ("https://evil.com/asbanc.com.pe", "el dominio en el path no cuenta"),
        ("https://asbanc.com.pe@evil.com/x", "userinfo: el host real es evil.com"),
        ("https://noasbanc.com.pe/x", "sufijo sin punto no es subdominio"),
        ("https://asbanc.com.pe.evil.com/x", "el dominio como prefijo tampoco"),
        ("https:///x", "host vacio"),
        ("no-es-una-url", "sin esquema ni host"),
        ("https://аsbanc.com.pe/x", "homografo: la primera letra es cirilica"),
    ],
)
def test_rechaza(url, por_que):
    assert not is_allowed(url, LISTA), por_que


def test_enforce_parte_en_dos_y_da_motivo():
    aceptadas, rechazadas = enforce(
        ["https://asbanc.com.pe/a", "https://evil.com/b", "http://sbs.gob.pe/c"],
        LISTA,
    )

    assert aceptadas == ("https://asbanc.com.pe/a",)
    assert len(rechazadas) == 2
    # El motivo distingue las dos clases de rechazo: una fuente prohibida no es
    # lo mismo que una URL rota, y el informe de gobernanza tiene que separarlas.
    assert "fuera del allowlist" in rechazadas[0].reason
    assert "no https" in rechazadas[1].reason


def test_lista_vacia_no_acepta_nada():
    """Un allowlist sin filas rechaza todo, no acepta todo.

    Es la misma inversión que el guard de `ENVIRONMENT`: la configuración
    ausente tiene que rechazar. Si la tabla queda vacía por un seed fallido, el
    corpus se queda sin crecer —que es visible— en vez de llenarse con cualquier
    fuente, que no lo es.
    """
    aceptadas, rechazadas = enforce(["https://asbanc.com.pe/a"], frozenset())
    assert aceptadas == ()
    assert len(rechazadas) == 1
