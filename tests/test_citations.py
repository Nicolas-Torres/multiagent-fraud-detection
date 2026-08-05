"""La citación por identidad y la unión de las dos piernas. Sin red, sin base.

Lo que se prueba acá es lo que ADR-0011 declara invariante. El nodo completo
—que además consulta el índice— se verifica en `scripts/smoke_decision.py`.
"""

import pytest

from multiagent_fraud_detection.domain.catalog import (
    Policy,
    PolicyCatalog,
    PolicyState,
)
from multiagent_fraud_detection.enums import DecisionType
from multiagent_fraud_detection.retrieval.citations import (
    authorization_citations,
    merge_citations,
    missing_authorization,
)
from multiagent_fraud_detection.schemas.decision import InternalCitation


def catalogo() -> PolicyCatalog:
    return PolicyCatalog(
        version="2025.1-b1",
        reference_currency="USD",
        policies=(
            Policy("FP-01", "2025.1", "Monto y horario", PolicyState.ACTIVE,
                   action=DecisionType.CHALLENGE),
            Policy("FP-03", "2025.1", "Velocity check", PolicyState.ACTIVE,
                   action=DecisionType.BLOCK),
            # Version distinta a proposito: la cita tiene que seguir a la
            # politica, no a una constante.
            Policy("FP-10", "2025.2", "No evaluable", PolicyState.EXCLUDED),
        ),
    )


def cita(policy_id="FP-99", chunk_id="FP-99:2025.1:0", version="2025.1"):
    return InternalCitation(policy_id=policy_id, chunk_id=chunk_id, version=version)


# --------------------------------------------------------------------------- #
# Autorización
# --------------------------------------------------------------------------- #


def test_cita_toda_politica_que_disparo():
    """Recall 1.0 por construcción: es lo que la pierna promete."""
    citas = authorization_citations(catalogo(), ["FP-03", "FP-01"])
    assert [c.policy_id for c in citas] == ["FP-01", "FP-03"]
    assert missing_authorization(citas, ["FP-01", "FP-03"]) == ()


def test_el_chunk_id_sigue_a_la_version_de_la_politica():
    """No a una constante: FP-10 vive en 2025.2 y su cita tiene que decirlo."""
    (c,) = authorization_citations(catalogo(), ["FP-10"])
    assert c.version == "2025.2"
    assert c.chunk_id == "FP-10:2025.2:0"


def test_sin_politicas_no_hay_citas():
    """El caso del 90% del tráfico: no dispara nada, no cita nada.

    Es lo que hace que el invariante se apague solo en vez de volver
    insatisfacible el `APPROVE`.
    """
    assert authorization_citations(catalogo(), []) == []
    assert missing_authorization([], []) == ()


def test_el_orden_es_estable():
    a = authorization_citations(catalogo(), ["FP-03", "FP-01"])
    b = authorization_citations(catalogo(), ["FP-01", "FP-03"])
    assert [c.chunk_id for c in a] == [c.chunk_id for c in b]


# --------------------------------------------------------------------------- #
# La unión
# --------------------------------------------------------------------------- #


def test_la_autorizacion_nunca_se_pierde_en_la_union():
    autorizadas = authorization_citations(catalogo(), ["FP-03"])
    descubiertas = [cita("FP-05", "FP-05:2025.1:0"), cita("FP-02", "FP-02:2025.1:0")]

    unidas = merge_citations(autorizadas, descubiertas)

    assert unidas[0].policy_id == "FP-03"
    assert missing_authorization(unidas, ["FP-03"]) == ()
    assert len(unidas) == 3


def test_llegar_por_las_dos_vias_no_son_dos_citas():
    autorizadas = authorization_citations(catalogo(), ["FP-03"])
    descubiertas = [cita("FP-03", "FP-03:2025.1:0")]

    unidas = merge_citations(autorizadas, descubiertas)

    assert len(unidas) == 1


def test_el_descubrimiento_solo_no_satisface_el_invariante():
    """El fallo silencioso que ADR-0011 cierra.

    El motor dispara FP-03 y el índice devuelve FP-05 y FP-02: sin la pierna de
    autorización el caso se decide `BLOCK` citando normas que no aplicó, y una
    guarda de "lista no vacía" lo deja pasar.
    """
    solo_descubrimiento = [
        cita("FP-05", "FP-05:2025.1:0"),
        cita("FP-02", "FP-02:2025.1:0"),
    ]

    assert solo_descubrimiento  # la formulación débil se cumple
    assert missing_authorization(solo_descubrimiento, ["FP-03"]) == ("FP-03",)


def test_missing_authorization_lista_todas_las_que_faltan():
    assert missing_authorization([], ["FP-03", "FP-01"]) == ("FP-01", "FP-03")


# --------------------------------------------------------------------------- #
# La guarda del persistidor
# --------------------------------------------------------------------------- #


def _estado(decision, *, policies, citations, base=0.4, confidence=None):
    return {
        "decision": decision,
        "policies": policies,
        "citations_internal": citations,
        "base_confidence": base,
        "confidence": base if confidence is None else confidence,
    }


def test_aprobar_sin_citas_es_valido():
    """El caso que la redacción anterior hacía imposible."""
    from multiagent_fraud_detection.graph.nodes import _verificar_invariantes

    _verificar_invariantes(_estado(DecisionType.APPROVE, policies=[], citations=[]))


def test_bloquear_sin_respaldo_levanta():
    from multiagent_fraud_detection.graph.nodes import _verificar_invariantes

    with pytest.raises(ValueError, match="FP-03"):
        _verificar_invariantes(
            _estado(DecisionType.BLOCK, policies=["FP-03"], citations=[])
        )


def test_bloquear_citando_otra_norma_levanta():
    """Lista no vacía, respaldo ausente: la diferencia entre las dos guardas."""
    from multiagent_fraud_detection.graph.nodes import _verificar_invariantes

    with pytest.raises(ValueError, match="FP-03"):
        _verificar_invariantes(
            _estado(
                DecisionType.BLOCK,
                policies=["FP-03"],
                citations=[cita("FP-05", "FP-05:2025.1:0")],
            )
        )


def test_escalar_queda_exento():
    from multiagent_fraud_detection.graph.nodes import _verificar_invariantes

    _verificar_invariantes(
        _estado(DecisionType.ESCALATE_TO_HUMAN, policies=["FP-03"], citations=[])
    )
