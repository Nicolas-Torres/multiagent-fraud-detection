"""Scoring y Evidence Aggregation.

El contrato pide dos números con comportamientos incompatibles entre sí —uno
monótono, otro en U— y estos tests son la garantía de que siguen siéndolo. Son
propiedades, no valores: si mañana se cambian los pesos, la mayoría debe seguir
pasando.
"""

from dataclasses import dataclass

import pytest

from multiagent_fraud_detection.domain.scoring import (
    MIN_CONFIDENCE,
    SCORING_VERSION,
    base_confidence,
    has_contradiction,
    risk_score,
    signal_sort_key,
)
from multiagent_fraud_detection.enums import DecisionType, Severity
from multiagent_fraud_detection.graph.nodes import AGGREGATE, evidence_aggregation
from multiagent_fraud_detection.graph.state import AgentError, WorkingSignal

H, M, L = Severity.HIGH, Severity.MEDIUM, Severity.LOW


def señal(code, severity=M, emitted_by="behavioral_pattern"):
    return WorkingSignal(
        code=code, description=code, severity=severity, emitted_by=emitted_by
    )


@pytest.fixture
def runtime(catalogo):
    @dataclass
    class Ctx:
        catalog: object

    @dataclass
    class Rt:
        context: object

    return Rt(Ctx(catalogo))


# --------------------------------------------------------------------------- #
# risk_score: monótono, conmutativo, acotado
# --------------------------------------------------------------------------- #


def test_sin_señales_el_riesgo_es_cero():
    assert risk_score([]) == 0.0


def test_agregar_evidencia_nunca_baja_el_riesgo():
    """Monotonía: es lo que hace al score utilizable para ordenar la cola."""
    anterior = 0.0
    for n in range(1, 8):
        actual = risk_score([M] * n)
        assert actual >= anterior
        anterior = actual


def test_el_orden_de_las_señales_no_cambia_el_riesgo():
    """Conmutatividad. Las señales llegan de dos agentes en paralelo: su orden
    de arribo es arbitrario y no puede afectar el número."""
    assert risk_score([H, L, M]) == risk_score([M, H, L]) == risk_score([L, M, H])


def test_el_riesgo_esta_acotado_sin_recorte_artificial():
    """Nunca pasa de 1, y no hace falta un `min()` para lograrlo.

    Matemáticamente el noisy-OR tiende a 1 sin alcanzarlo; con redondeo a cuatro
    decimales satura en 1.0 alrededor de la señal grave número catorce. Que
    sature por redondeo y no por recorte importa: un `min(1, ...)` escondería una
    fórmula que sí puede pasarse.
    """
    assert risk_score([H] * 30) == 1.0
    assert risk_score([H] * 5) < 1.0


def test_una_señal_grave_pesa_mas_que_una_leve():
    assert risk_score([H]) > risk_score([M]) > risk_score([L])


def test_la_evidencia_acumulada_satura():
    """La quinta señal media pesa menos que la primera: así funciona la evidencia."""
    primera = risk_score([M]) - risk_score([])
    quinta = risk_score([M] * 5) - risk_score([M] * 4)
    assert quinta < primera


# --------------------------------------------------------------------------- #
# base_confidence: forma de U
# --------------------------------------------------------------------------- #


def test_la_confianza_tiene_forma_de_u():
    """Máxima en los extremos, mínima en el medio.

    Es la razón por la que el contrato expone dos números: ninguna función
    monótona hace esto y ordena la cola al mismo tiempo.
    """
    extremo_bajo = base_confidence(0.0)
    medio = base_confidence(0.5)
    extremo_alto = base_confidence(1.0)

    assert extremo_bajo == extremo_alto == 1.0
    assert medio < extremo_bajo
    assert medio == 0.5


def test_un_agente_caido_baja_la_confianza_sin_mover_el_riesgo():
    """La propiedad central del contrato: una falla no es evidencia de fraude."""
    riesgo = risk_score([H, M])
    completa = base_confidence(riesgo)
    degradada = base_confidence(riesgo, degraded_agents=["external_threat_intel"])

    assert degradada < completa
    assert risk_score([H, M]) == riesgo  # el riesgo no se tocó


def test_cada_agente_caido_penaliza_por_separado():
    uno = base_confidence(1.0, degraded_agents=["a"])
    dos = base_confidence(1.0, degraded_agents=["a", "b"])
    assert dos < uno


def test_la_contradiccion_baja_la_confianza():
    assert base_confidence(0.8, contradiction=True) < base_confidence(0.8)


def test_la_falta_de_perfil_baja_la_confianza():
    assert base_confidence(0.8, missing_profile=True) < base_confidence(0.8)


def test_la_confianza_tiene_piso():
    """Cero significaría "sin información", y siempre hay alguna: al menos la de
    saber que la evidencia está incompleta."""
    peor = base_confidence(0.5, degraded_agents=["a", "b", "c", "d"],
                           contradiction=True, missing_profile=True)
    assert peor == MIN_CONFIDENCE


def test_la_confianza_nunca_pasa_de_uno():
    assert base_confidence(1.0) <= 1.0


# --------------------------------------------------------------------------- #
# Contradicción y orden
# --------------------------------------------------------------------------- #


def test_dos_politicas_que_mandan_lo_mismo_no_son_contradiccion():
    assert not has_contradiction([DecisionType.BLOCK, DecisionType.BLOCK])


def test_dos_politicas_que_mandan_distinto_si_lo_son():
    assert has_contradiction([DecisionType.BLOCK, DecisionType.CHALLENGE])


def test_una_politica_sola_no_contradice_a_nadie():
    assert not has_contradiction([DecisionType.BLOCK])
    assert not has_contradiction([])


def test_el_orden_es_por_severidad_y_luego_codigo():
    codigos = [("Z_LOW", L), ("A_HIGH", H), ("B_HIGH", H), ("M_MEDIUM", M)]
    ordenados = sorted(codigos, key=lambda c: signal_sort_key(*c))
    assert [c for c, _ in ordenados] == ["A_HIGH", "B_HIGH", "M_MEDIUM", "Z_LOW"]


# --------------------------------------------------------------------------- #
# El nodo
# --------------------------------------------------------------------------- #


async def test_deduplica_lo_que_llega_de_los_dos_agentes(runtime):
    estado = {
        "signals": [
            señal("NEW_DEVICE", emitted_by="behavioral_pattern"),
            señal("NEW_DEVICE", emitted_by="transaction_context"),
        ]
    }
    salida = await evidence_aggregation(estado, runtime)
    assert [s.code for s in salida["evidence"]] == ["NEW_DEVICE"]


async def test_ordena_por_severidad_descendente(runtime):
    estado = {
        "signals": [
            señal("B_LOW", L),
            señal("A_HIGH", H),
            señal("C_MEDIUM", M),
        ]
    }
    salida = await evidence_aggregation(estado, runtime)
    assert [s.code for s in salida["evidence"]] == ["A_HIGH", "C_MEDIUM", "B_LOW"]


async def test_el_acumulador_no_se_toca(runtime):
    """`signals` es aditivo: devolverlo consolidado lo concatenaría y duplicaría
    todo. Por eso la evidencia consolidada vive en otra clave."""
    estado = {"signals": [señal("A"), señal("A")]}
    salida = await evidence_aggregation(estado, runtime)

    assert "signals" not in salida
    assert "matched_policies" not in salida


async def test_produce_los_tres_campos_de_scoring(runtime):
    salida = await evidence_aggregation({"signals": [señal("A", H)]}, runtime)

    assert 0.0 < salida["risk_score"] <= 1.0
    assert 0.0 < salida["base_confidence"] <= 1.0
    assert salida["scoring_version"] == SCORING_VERSION


async def test_un_caso_limpio_da_riesgo_cero_y_confianza_maxima(runtime):
    """Ninguna señal es un `APPROVE` claro, no una duda."""
    salida = await evidence_aggregation({}, runtime)

    assert salida["risk_score"] == 0.0
    assert salida["base_confidence"] == 1.0
    assert salida["evidence"] == []


async def test_un_agente_caido_baja_la_confianza_del_caso(runtime):
    limpio = await evidence_aggregation({"signals": [señal("A", H)]}, runtime)
    roto = await evidence_aggregation(
        {
            "signals": [señal("A", H)],
            "agent_errors": [
                AgentError(agent="external_threat_intel", error_type="TimeoutError",
                           message="timeout")
            ],
        },
        runtime,
    )

    assert roto["risk_score"] == limpio["risk_score"]
    assert roto["base_confidence"] < limpio["base_confidence"]


async def test_politicas_que_mandan_distinto_bajan_la_confianza(runtime):
    """FP-01 pide CHALLENGE, FP-09 pide BLOCK. Las dos pueden aplicar."""
    señales = [señal("A", H)]
    sola = await evidence_aggregation(
        {"signals": señales, "matched_policies": ["FP-09"]}, runtime
    )
    ambas = await evidence_aggregation(
        {"signals": señales, "matched_policies": ["FP-01", "FP-09"]}, runtime
    )

    assert ambas["base_confidence"] < sola["base_confidence"]


async def test_la_ausencia_de_perfil_no_sube_el_riesgo(runtime):
    """"No pude comparar" no es "esto es sospechoso".

    Es el mismo error de categoría que contar un agente caído como evidencia de
    fraude, y castigaría a las ~96 transacciones sin perfil por algo que no es
    de ellas.
    """
    con = await evidence_aggregation({"signals": [señal("A", H)]}, runtime)
    sin = await evidence_aggregation(
        {"signals": [señal("A", H), señal("NO_CUSTOMER_PROFILE", M)]}, runtime
    )

    assert sin["risk_score"] == con["risk_score"]
    assert sin["base_confidence"] < con["base_confidence"]


async def test_las_politicas_salen_ordenadas_y_sin_repetir(runtime):
    salida = await evidence_aggregation(
        {"signals": [], "matched_policies": ["FP-09", "FP-01", "FP-09"]}, runtime
    )
    assert salida["policies"] == ["FP-01", "FP-09"]


async def test_el_nodo_se_anota_en_la_ruta(runtime):
    salida = await evidence_aggregation({}, runtime)
    assert salida["agent_route"] == [AGGREGATE]
