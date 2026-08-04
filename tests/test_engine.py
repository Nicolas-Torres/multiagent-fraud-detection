"""El intérprete.

Dos comportamientos que no son obvios y que un refactor puede romper sin que
`check_policies.py` se entere —porque no cambian `matched_policies`—:

1. **No corta.** Una señal cierta se emite aunque su política no complete.
2. **Deduplica.** Un mismo código producido por varias políticas es una señal,
   con la trazabilidad acumulada.
"""

from decimal import Decimal

from multiagent_fraud_detection.domain.catalog import Owner
from multiagent_fraud_detection.domain.engine import (
    evaluate,
    evaluate_policy,
    prescribed_action,
)
from multiagent_fraud_detection.domain.predicates import EvalContext
from multiagent_fraud_detection.enums import DecisionType

from conftest import utc


def ctx(tx, perfil=None, **kw):
    return EvalContext(
        tx,
        perfil,
        tuple(kw.get("hist", ())),
        tuple(kw.get("dev", ())),
        kw.get("blacklist", frozenset()),
    )


# --------------------------------------------------------------------------- #
# No cortar en el primer predicado que falla
# --------------------------------------------------------------------------- #


def test_una_señal_cierta_se_emite_aunque_su_politica_no_complete(tx, perfil, catalogo):
    """4× el promedio a las 10:00: FP-01 no matchea, pero el monto SÍ es atípico.

    Con corte en el primer fallo esta señal se perdería, y es justo la clase de
    observación que el Arbiter tiene que ponderar: la que no viene con una
    política que la explique.
    """
    caso = ctx(tx(amount=Decimal("4000.00"), timestamp=utc(2026, 3, 10, 15, 0)), perfil)
    ev = evaluate(catalogo, Owner.BEHAVIORAL, caso)

    assert "FP-01" not in ev.matched_policies
    assert "AMOUNT_OVER_USUAL_AVG" in {s.code for s in ev.signals}
    assert "OUTSIDE_USUAL_HOURS" not in {s.code for s in ev.signals}


def test_politica_completa_matchea_y_emite_todas_sus_señales(tx, perfil, catalogo):
    """4× el promedio a las 21:00 de Lima: FP-01 completa."""
    caso = ctx(tx(amount=Decimal("4000.00"), timestamp=utc(2026, 3, 11, 2, 0)), perfil)
    ev = evaluate(catalogo, Owner.BEHAVIORAL, caso)

    assert "FP-01" in ev.matched_policies
    assert {"AMOUNT_OVER_USUAL_AVG", "OUTSIDE_USUAL_HOURS"} <= {s.code for s in ev.signals}


def test_evaluate_policy_devuelve_señales_y_veredicto_por_separado(tx, perfil, catalogo):
    señales, matched = evaluate_policy(
        catalogo["FP-01"], ctx(tx(amount=Decimal("4000.00")), perfil)
    )
    assert matched is False
    assert len(señales) == 1


# --------------------------------------------------------------------------- #
# Señales no-standalone
# --------------------------------------------------------------------------- #


def test_umbral_absoluto_no_se_emite_si_su_politica_no_matchea(tx, catalogo):
    """Sin lista negra, "monto sobre 135 USD" dispararía en el 90% del dataset.

    Una señal con esa tasa base no es evidencia: es ruido que inunda la tabla que
    el entregable 6 vigila. Por eso `amount_over_absolute` no es standalone.
    """
    caso = ctx(tx(amount=Decimal("9999.00"), merchant_id="M-001"))
    ev = evaluate(catalogo, Owner.CONTEXT, caso)

    assert ev.matched_policies == ()
    assert ev.signals == ()


def test_umbral_absoluto_se_emite_cuando_fp07_completa(tx, catalogo):
    caso = ctx(tx(amount=Decimal("9999.00"), merchant_id="M-999"), blacklist=frozenset({"M-999"}))
    ev = evaluate(catalogo, Owner.CONTEXT, caso)

    assert ev.matched_policies == ("FP-07",)
    assert {s.code for s in ev.signals} == {"MERCHANT_BLACKLISTED", "AMOUNT_OVER_ABSOLUTE"}


# --------------------------------------------------------------------------- #
# Deduplicación y trazabilidad
# --------------------------------------------------------------------------- #


def test_una_señal_de_varias_politicas_se_deduplica_conservando_el_origen(
    tx, perfil, catalogo
):
    """`AMOUNT_OVER_USUAL_AVG` sale de FP-01 (3×), FP-04 (2×) y FP-06 (2×)."""
    caso = ctx(tx(amount=Decimal("4000.00"), channel="mobile"), perfil)
    ev = evaluate(catalogo, Owner.BEHAVIORAL, caso)

    monto = [s for s in ev.signals if s.code == "AMOUNT_OVER_USUAL_AVG"]
    assert len(monto) == 1
    assert set(monto[0].from_policies) >= {"FP-01", "FP-04", "FP-06"}


def test_el_orden_de_las_señales_es_estable(tx, perfil, catalogo):
    """Dos corridas idénticas, el mismo orden. Sin esto el diff del harness es ruido."""
    caso = ctx(tx(amount=Decimal("4000.00"), channel="mobile", country="ES"), perfil)
    primera = [s.code for s in evaluate(catalogo, Owner.BEHAVIORAL, caso).signals]
    segunda = [s.code for s in evaluate(catalogo, Owner.BEHAVIORAL, caso).signals]
    assert primera == segunda


# --------------------------------------------------------------------------- #
# Despacho y consolidación
# --------------------------------------------------------------------------- #


def test_sin_perfil_las_politicas_de_contraste_quedan_omitidas(tx, catalogo):
    """No fallan: se registran en `skipped_policies`. Es evidencia degradada."""
    ev = evaluate(catalogo, Owner.BEHAVIORAL, ctx(tx()))

    assert "FP-01" in ev.skipped_policies
    assert "FP-02" in ev.skipped_policies
    assert ev.matched_policies == ()


def test_context_sigue_produciendo_evidencia_sin_perfil(tx, catalogo):
    """Es el piso de evidencia: el agente que funciona cuando el cliente no existe."""
    caso = ctx(tx(amount=Decimal("9999.00"), merchant_id="M-999"), blacklist=frozenset({"M-999"}))
    ev = evaluate(catalogo, Owner.CONTEXT, caso)
    assert ev.matched_policies == ("FP-07",)


def test_merge_une_los_dos_agentes(tx, perfil, catalogo):
    caso = ctx(
        tx(amount=Decimal("9999.00"), merchant_id="M-999", timestamp=utc(2026, 3, 11, 2, 0)),
        perfil,
        blacklist=frozenset({"M-999"}),
    )
    ev = evaluate(catalogo, Owner.CONTEXT, caso).merge(
        evaluate(catalogo, Owner.BEHAVIORAL, caso)
    )

    assert "FP-07" in ev.matched_policies
    assert "FP-01" in ev.matched_policies
    assert len({s.code for s in ev.signals}) == len(ev.signals)  # sin duplicados


# --------------------------------------------------------------------------- #
# Precedencia
# --------------------------------------------------------------------------- #


def test_sin_politicas_la_accion_es_aprobar(catalogo):
    assert prescribed_action(catalogo, ()) is DecisionType.APPROVE


def test_gana_la_politica_mas_restrictiva(catalogo):
    """FP-01 pide CHALLENGE y FP-09 pide BLOCK: manda BLOCK."""
    assert prescribed_action(catalogo, ("FP-01", "FP-09")) is DecisionType.BLOCK
    assert prescribed_action(catalogo, ("FP-01", "FP-02")) is DecisionType.ESCALATE_TO_HUMAN
    assert prescribed_action(catalogo, ("FP-01",)) is DecisionType.CHALLENGE


def test_la_precedencia_no_depende_del_orden(catalogo):
    assert prescribed_action(catalogo, ("FP-09", "FP-01")) is prescribed_action(
        catalogo, ("FP-01", "FP-09")
    )
