"""Carga y validación del catálogo.

Con las reglas como dato, la validación se corre de tiempo de compilación a
tiempo de carga (ADR-0007). Estos tests son lo que reemplaza al compilador: cada
uno es una forma de romper un catálogo que antes habría sido un `SyntaxError`.

La otra mitad es la distinción entre **error** y **estado**: un catálogo mal
formado frena el arranque; que el banco edite un texto no puede dejar el motor
fuera de servicio.
"""

import copy
import json

import pytest

from multiagent_fraud_detection.domain.catalog import (
    CatalogError,
    Owner,
    PolicyState,
    fingerprint,
    load_catalog,
    predicate_library_spec,
)

from conftest import POLICIES


@pytest.fixture
def escribir(tmp_path):
    """Carga el catálogo real, lo muta y lo escribe en un temporal."""
    docs = json.loads((POLICIES / "fraud_policies_2025.1.json").read_text(encoding="utf-8"))
    binds = json.loads((POLICIES / "policy_bindings_2025.1.json").read_text(encoding="utf-8"))

    def make(mutar_docs=None, mutar_binds=None):
        d, b = copy.deepcopy(docs), copy.deepcopy(binds)
        if mutar_docs:
            mutar_docs(d)
        if mutar_binds:
            mutar_binds(b)
        (tmp_path / "d.json").write_text(json.dumps(d), encoding="utf-8")
        (tmp_path / "b.json").write_text(json.dumps(b), encoding="utf-8")
        return tmp_path / "d.json", tmp_path / "b.json"

    return make


# --------------------------------------------------------------------------- #
# El catálogo real
# --------------------------------------------------------------------------- #


def test_el_catalogo_del_repo_carga_limpio(catalogo):
    assert catalogo.health == {"active": 10, "excluded": 1, "pending": 0, "stale": 0}


def test_el_reparto_context_behavioral_se_deriva(catalogo):
    """1 contra 9, y no lo eligió nadie: sale de los insumos de cada predicado."""
    assert [p.policy_id for p in catalogo.evaluable_by(Owner.CONTEXT)] == ["FP-07"]
    assert len(catalogo.evaluable_by(Owner.BEHAVIORAL)) == 9


def test_las_politicas_salen_ordenadas(catalogo):
    """El orden es contrato con el harness: sin él, el diff es ruido."""
    ids = [p.policy_id for p in catalogo.evaluable_by(Owner.BEHAVIORAL)]
    assert ids == sorted(ids)


def test_fp10_es_una_exclusion_registrada_no_un_hueco(catalogo):
    fp10 = catalogo["FP-10"]
    assert fp10.state is PolicyState.EXCLUDED
    assert "ADR-0005" in fp10.excluded_reason
    assert not fp10.evaluable


def test_toda_vinculacion_esta_firmada(catalogo):
    for p in catalogo.policies:
        if p.state is not PolicyState.PENDING:
            assert p.bound_by


# --------------------------------------------------------------------------- #
# Estados: el banco toca sus documentos y el motor degrada
# --------------------------------------------------------------------------- #


def test_texto_editado_marca_la_vinculacion_obsoleta(escribir):
    """El banco cambia "3x" por "4x": FP-01 deja de evaluarse y sigue citable."""
    d, b = escribir(mutar_docs=lambda x: x[0].__setitem__("rule", x[0]["rule"].replace("3x", "4x")))
    cat = load_catalog(d, b)

    assert cat["FP-01"].state is PolicyState.STALE
    assert not cat["FP-01"].evaluable
    assert cat["FP-01"].text  # el texto nuevo sigue disponible para el RAG
    assert cat.health["stale"] == 1


def test_politica_nueva_sin_traducir_queda_pendiente(escribir):
    """Se publica hoy y el RAG la cita hoy, aunque nadie la haya vinculado."""
    d, b = escribir(
        mutar_docs=lambda x: x.append(
            {"policy_id": "FP-12", "rule": "Regla nueva del banco", "version": "2025.2"}
        )
    )
    cat = load_catalog(d, b)

    assert cat["FP-12"].state is PolicyState.PENDING
    assert cat["FP-12"].text == "Regla nueva del banco"
    assert cat["FP-12"].condition == ()


def test_desactivar_una_vinculacion_la_saca_del_motor(escribir):
    d, b = escribir(mutar_binds=lambda x: x["bindings"][0].__setitem__("active", False))
    cat = load_catalog(d, b)
    assert not cat["FP-01"].evaluable


def test_la_huella_se_calcula_solo_sobre_el_texto(escribir):
    """Un typo corregido en metadatos no invalida una traducción correcta."""
    d, b = escribir(mutar_docs=lambda x: x[0].__setitem__("version", "2025.1 "))
    cat = load_catalog(d, b)
    assert cat["FP-01"].state is PolicyState.ACTIVE


def test_la_huella_del_repo_corresponde_al_texto_del_repo():
    docs = json.loads((POLICIES / "fraud_policies_2025.1.json").read_text(encoding="utf-8"))
    binds = json.loads((POLICIES / "policy_bindings_2025.1.json").read_text(encoding="utf-8"))
    por_id = {d["policy_id"]: d["rule"] for d in docs}
    for v in binds["bindings"]:
        assert v["source_fingerprint"] == fingerprint(por_id[v["policy_id"]])


# --------------------------------------------------------------------------- #
# Errores: el catálogo mal formado no arranca
# --------------------------------------------------------------------------- #


def test_predicado_inexistente(escribir):
    d, b = escribir(
        mutar_binds=lambda x: x["bindings"][0]["condition"][0].__setitem__(
            "predicate", "monto_grande"
        )
    )
    with pytest.raises(CatalogError, match="predicado desconocido"):
        load_catalog(d, b)


def test_parametro_fuera_de_rango(escribir):
    d, b = escribir(
        mutar_binds=lambda x: x["bindings"][0]["condition"][0]["params"].__setitem__("factor", 0.5)
    )
    with pytest.raises(CatalogError, match="menor que"):
        load_catalog(d, b)


def test_parametro_faltante(escribir):
    d, b = escribir(mutar_binds=lambda x: x["bindings"][0]["condition"][0].__setitem__("params", {}))
    with pytest.raises(CatalogError, match="faltan parámetros"):
        load_catalog(d, b)


def test_accion_approve_es_invalida(escribir):
    """Ninguna política prescribe aprobar: `APPROVE` es la ausencia de política."""
    d, b = escribir(mutar_binds=lambda x: x["bindings"][0].__setitem__("action", "APPROVE"))
    with pytest.raises(CatalogError, match="APPROVE"):
        load_catalog(d, b)


def test_exclusion_sin_motivo(escribir):
    """`condition: null` sin motivo confunde "excluida" con "pendiente"."""
    d, b = escribir(mutar_binds=lambda x: x["bindings"][9].pop("excluded_reason"))
    with pytest.raises(CatalogError, match="excluded_reason"):
        load_catalog(d, b)


def test_condicion_que_abarca_los_dos_nodos(escribir):
    """Context y Behavioral corren en paralelo: ninguno la podría evaluar entera."""

    def cruzar(x):
        x["bindings"][6]["condition"] = [
            {"predicate": "merchant_blacklisted", "params": {}},
            {"predicate": "device_not_usual", "params": {}},
        ]

    d, b = escribir(mutar_binds=cruzar)
    with pytest.raises(CatalogError, match="abarca Context y Behavioral"):
        load_catalog(d, b)


def test_vinculacion_sin_documento(escribir):
    d, b = escribir(
        mutar_binds=lambda x: x["bindings"].append(
            {"policy_id": "FP-99", "action": "BLOCK", "condition": [], "active": True}
        )
    )
    with pytest.raises(CatalogError, match="sin documento"):
        load_catalog(d, b)


def test_los_problemas_se_reportan_todos_juntos(escribir):
    """Quien corrige un catálogo quiere la lista completa, no el primero."""

    def romper(x):
        x["bindings"][0]["condition"][0]["params"]["factor"] = 0.5
        x["bindings"][1]["action"] = "APPROVE"

    d, b = escribir(mutar_binds=romper)
    with pytest.raises(CatalogError) as e:
        load_catalog(d, b)
    assert len(e.value.problems) == 2


# --------------------------------------------------------------------------- #
# La biblioteca como dato (compositor del dashboard)
# --------------------------------------------------------------------------- #


def test_la_biblioteca_se_serializa_para_el_dashboard():
    spec = predicate_library_spec()
    assert len(spec) == 14

    factor = next(s for s in spec if s["name"] == "amount_over_avg_multiple")["params"]["factor"]
    assert factor["kind"] == "number"
    assert factor["minimum"] == 1.0
    assert factor["label"]

    eje = next(s for s in spec if s["name"] == "count_in_window")["params"]["axis"]
    assert eje["choices"] == ["device", "customer"]

    json.dumps(spec, default=str)  # tiene que poder viajar por HTTP
