"""La ruta catch-all del dashboard sólo sirve archivos de `dist/` (incidente 0012).

`/..%2F..%2Fpyproject.toml` devolvía el archivo del contenedor en producción:
`full_path` llega decodificado y se unía a `dist/` sin resolverlo.
"""

import pytest
from fastapi.testclient import TestClient

from multiagent_fraud_detection.api import app as app_module
from multiagent_fraud_detection.api.app import archivo_del_spa, create_app


@pytest.fixture
def dist(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html>indice", encoding="utf-8")
    (dist / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    (tmp_path / "secreto.env").write_text("CLAVE=no-debe-salir", encoding="utf-8")
    return dist


@pytest.mark.parametrize(
    ("full_path", "esperado"),
    [
        ("favicon.svg", "favicon.svg"),
        ("", "index.html"),
        ("cases/123", "index.html"),
        ("no-existe.js", "index.html"),
    ],
)
def test_sirve_los_archivos_de_dist_y_si_no_el_indice(dist, full_path, esperado):
    assert archivo_del_spa(dist, full_path) == (dist / esperado).resolve()


@pytest.mark.parametrize(
    "full_path",
    ["../secreto.env", "assets/../../secreto.env", "SECRETO_ABSOLUTO"],
)
def test_una_ruta_fuera_de_dist_cae_al_indice(dist, full_path):
    if full_path == "SECRETO_ABSOLUTO":
        full_path = str(dist.parent / "secreto.env")
    assert archivo_del_spa(dist, full_path) == (dist / "index.html").resolve()


@pytest.fixture
def cliente(dist, monkeypatch):
    monkeypatch.setattr(app_module, "DASHBOARD_DIST", dist)
    with TestClient(create_app()) as client:
        yield client


@pytest.mark.parametrize(
    "ruta", ["/..%2Fsecreto.env", "/%2e%2e/secreto.env", "/..%2F..%2Fdist%2F..%2Fsecreto.env"]
)
def test_por_http_el_recorrido_de_directorios_no_sale_de_dist(cliente, ruta):
    respuesta = cliente.get(ruta)

    assert respuesta.status_code == 200
    assert "no-debe-salir" not in respuesta.text
    assert respuesta.text == "<!doctype html>indice"


def test_una_ruta_de_api_inexistente_es_404_y_no_la_pagina(cliente):
    respuesta = cliente.get("/api/v1/no-existe")

    assert respuesta.status_code == 404
    assert respuesta.headers["content-type"].startswith("application/json")
