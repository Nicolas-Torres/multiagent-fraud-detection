"""Los catorce predicados, caso por caso.

No se testea que "funcionen": eso lo prueba `check_policies.py` sobre las 7 000.
Acá se testean los **bordes que el dataset no cubre o cubre por accidente**: el
cruce de medianoche, las listas vacías, el cliente sin perfil, el cambio de perfil
posterior al cargo. Son los casos donde una implementación plausible falla en
silencio.
"""

from datetime import timedelta
from decimal import Decimal

import pytest

from multiagent_fraud_detection.domain.predicates import (
    LIBRARY,
    CONTEXT_INPUTS,
    EvalContext,
    account_age_below,
    amount_over_absolute,
    amount_over_avg_multiple,
    amount_over_segment_multiple,
    channel_not_usual,
    count_in_window,
    country_not_usual,
    daily_sum_over_limit,
    device_not_usual,
    distinct_country_in_window,
    merchant_blacklisted,
    outside_usual_hours,
    preceding_micro_charges,
    profile_changed_within,
)

from conftest import utc


def ctx(tx, perfil=None, *, hist=(), dev=(), blacklist=frozenset()):
    return EvalContext(tx, perfil, tuple(hist), tuple(dev), blacklist)


# --------------------------------------------------------------------------- #
# Monto
# --------------------------------------------------------------------------- #


def test_monto_sobre_multiplo_dispara_y_trae_evidencia(tx, perfil):
    hit = amount_over_avg_multiple(ctx(tx(amount=Decimal("3000.01")), perfil), factor=3)
    assert hit is not None
    assert hit.observed["threshold"] == "3000.00"
    assert "3000.01" in hit.detail


def test_monto_exactamente_en_el_umbral_no_dispara(tx, perfil):
    """El umbral es estricto: 3× exacto **no** es "más de 3×"."""
    assert amount_over_avg_multiple(ctx(tx(amount=Decimal("3000.00")), perfil), factor=3) is None


def test_umbral_absoluto_se_convierte_a_la_moneda_del_cargo(tx):
    """135 USD son 499.50 PEN con el factor 3.7. Un literal por moneda sería un bug."""
    assert amount_over_absolute(ctx(tx(amount=Decimal("500.00"))), threshold_ref=135.0)
    assert amount_over_absolute(ctx(tx(amount=Decimal("499.00"))), threshold_ref=135.0) is None


def test_umbral_de_segmento_usa_el_promedio_congelado(tx, perfil):
    """retail = 634.3463... USD × 3.7 (PEN) × 5 ≈ 11 735.41."""
    assert amount_over_segment_multiple(ctx(tx(amount=Decimal("11736.00")), perfil), factor=5)
    assert amount_over_segment_multiple(ctx(tx(amount=Decimal("11735.00")), perfil), factor=5) is None


# --------------------------------------------------------------------------- #
# Horario — el borde que ya causó un bug documentado
# --------------------------------------------------------------------------- #


def test_horario_se_evalua_en_la_zona_del_perfil(tx, perfil):
    """15:00 UTC son las 10:00 en Lima: dentro de 08–20.

    Evaluado en UTC daría 15 —también dentro—, así que este caso no distingue.
    El siguiente sí.
    """
    assert outside_usual_hours(ctx(tx(timestamp=utc(2026, 3, 10, 15, 0)), perfil)) is None


def test_el_supuesto_america_lima_esta_muerto(tx, perfil):
    """02:00 UTC son las 21:00 del día anterior en Lima: **fuera** de 08–20.

    En UTC daría 02 —también fuera— pero por la razón equivocada. Este test falla
    si alguien vuelve a hardcodear una zona: con `America/Santiago` (UTC-3) serían
    las 23:00, también fuera, pero `hit.observed["local_hour"]` sería 23 y no 21.
    """
    hit = outside_usual_hours(ctx(tx(timestamp=utc(2026, 3, 10, 2, 0)), perfil))
    assert hit is not None
    assert hit.observed["local_hour"] == 21
    assert hit.observed["timezone"] == "America/Lima"


def test_ventana_nocturna_cruza_medianoche(tx, perfil):
    """Un cliente que opera 22–06 es válido: `start > end` no está prohibido."""
    nocturno = perfil.model_copy(update={"usual_hour_start": 22, "usual_hour_end": 6})
    # 05:00 UTC = 00:00 en Lima → dentro de 22–06
    assert outside_usual_hours(ctx(tx(timestamp=utc(2026, 3, 10, 5, 0)), nocturno)) is None
    # 17:00 UTC = 12:00 en Lima → fuera
    assert outside_usual_hours(ctx(tx(timestamp=utc(2026, 3, 10, 17, 0)), nocturno)) is not None


def test_ventana_inclusiva_en_los_dos_extremos(tx, perfil):
    """`08-20` incluye las 20:45: la hora se compara, no el instante."""
    assert outside_usual_hours(ctx(tx(timestamp=utc(2026, 3, 11, 1, 45)), perfil)) is None


# --------------------------------------------------------------------------- #
# Listas del perfil — vacío significa "todo es nuevo"
# --------------------------------------------------------------------------- #


def test_lista_de_paises_vacia_hace_ajeno_todo_pais(tx, perfil):
    sin_paises = perfil.model_copy(update={"usual_countries": []})
    hit = country_not_usual(ctx(tx(country="PE"), sin_paises))
    assert hit is not None
    assert "ninguno registrado" in hit.detail


def test_lista_de_dispositivos_vacia_hace_nuevo_todo_dispositivo(tx, perfil):
    sin_disp = perfil.model_copy(update={"usual_devices": []})
    assert device_not_usual(ctx(tx(device_id="D-0001"), sin_disp)) is not None


def test_pais_y_dispositivo_habituales_no_disparan(tx, perfil):
    assert country_not_usual(ctx(tx(), perfil)) is None
    assert device_not_usual(ctx(tx(), perfil)) is None
    assert channel_not_usual(ctx(tx(), perfil)) is None


def test_canal_distinto_dispara(tx, perfil):
    assert channel_not_usual(ctx(tx(channel="mobile"), perfil)) is not None


# --------------------------------------------------------------------------- #
# Tiempo del perfil
# --------------------------------------------------------------------------- #


def test_cuenta_nueva(tx, perfil):
    reciente = perfil.model_copy(
        update={"account_creation_date": tx().timestamp.date() - timedelta(days=10)}
    )
    hit = account_age_below(ctx(tx(), reciente), days=30)
    assert hit.observed["account_age_days"] == 10
    assert account_age_below(ctx(tx(), perfil), days=30) is None


def test_cambio_de_perfil_solo_cuenta_hacia_adelante(tx, perfil):
    """Un cambio **posterior** al cargo no lo explica.

    Sin el borde inferior, cualquier cargo anterior al último cambio dispararía.
    """
    t = utc(2026, 3, 10, 15, 0)
    antes = perfil.model_copy(update={"last_profile_update": t - timedelta(minutes=10)})
    despues = perfil.model_copy(update={"last_profile_update": t + timedelta(minutes=10)})
    assert profile_changed_within(ctx(tx(timestamp=t), antes), minutes=30) is not None
    assert profile_changed_within(ctx(tx(timestamp=t), despues), minutes=30) is None


# --------------------------------------------------------------------------- #
# Lista negra
# --------------------------------------------------------------------------- #


def test_lista_negra(tx):
    assert merchant_blacklisted(ctx(tx(merchant_id="M-999"), blacklist=frozenset({"M-999"})))
    assert merchant_blacklisted(ctx(tx(merchant_id="M-999"), blacklist=frozenset())) is None


# --------------------------------------------------------------------------- #
# Secuencia
# --------------------------------------------------------------------------- #


def test_velocidad_por_dispositivo_cruza_cuentas(tx):
    """El eje `device` no filtra por cliente: es la razón de ser de la política."""
    t = utc(2026, 3, 10, 15, 0)
    previas = [
        tx(transaction_id=f"T-{i}", customer_id=f"CU-{i}", timestamp=t - timedelta(minutes=i))
        for i in (1, 2, 3)
    ]
    hit = count_in_window(
        ctx(tx(timestamp=t), dev=previas), axis="device", window_minutes=5, min_count=4
    )
    assert hit is not None and hit.observed["count"] == 4


def test_velocidad_ignora_lo_que_cae_fuera_de_la_ventana(tx):
    t = utc(2026, 3, 10, 15, 0)
    previas = [
        tx(transaction_id="T-a", timestamp=t - timedelta(minutes=1)),
        tx(transaction_id="T-b", timestamp=t - timedelta(minutes=2)),
        tx(transaction_id="T-c", timestamp=t - timedelta(minutes=6)),  # fuera
    ]
    assert (
        count_in_window(
            ctx(tx(timestamp=t), dev=previas), axis="device", window_minutes=5, min_count=4
        )
        is None
    )


def test_cargos_de_prueba_previos(tx):
    t = utc(2026, 3, 10, 15, 0)
    micro = [
        tx(transaction_id=f"T-{i}", amount=Decimal("2.00"), timestamp=t - timedelta(minutes=i))
        for i in (1, 2)
    ]
    hit = preceding_micro_charges(
        ctx(tx(timestamp=t), hist=micro), min_count=2, ceiling_ref=1.0, window_minutes=10
    )
    assert hit is not None  # techo = 1.0 USD × 3.7 = 3.70 PEN


def test_pais_distinto_en_ventana_corta(tx):
    t = utc(2026, 3, 10, 15, 0)
    previa = tx(transaction_id="T-a", country="ES", timestamp=t - timedelta(hours=1))
    hit = distinct_country_in_window(ctx(tx(timestamp=t), hist=[previa]), window_minutes=120)
    assert hit.observed["previous_country"] == "ES"
    assert hit.observed["minutes_apart"] == 60


def test_suma_diaria_usa_el_dia_local_del_cliente(tx, perfil):
    """03:00 UTC del día 11 son las 22:00 del día 10 en Lima: mismo día local.

    En UTC serían días distintos y la política no dispararía. Es el caso que
    justifica resolver la fecha en la zona del perfil.
    """
    t = utc(2026, 3, 11, 3, 0)
    previas = [
        tx(transaction_id="T-a", amount=Decimal("2000.00"), timestamp=t - timedelta(hours=1)),
        tx(transaction_id="T-b", amount=Decimal("2000.00"), timestamp=t - timedelta(hours=2)),
    ]
    hit = daily_sum_over_limit(
        ctx(tx(timestamp=t, amount=Decimal("2000.00")), perfil, hist=previas),
        group_by="merchant",
        min_count=3,
    )
    assert hit is not None
    assert hit.observed["local_date"] == "2026-03-10"
    assert hit.observed["sum"] == "6000.00"  # sobre el límite de 5000


# --------------------------------------------------------------------------- #
# Invariantes de la biblioteca
# --------------------------------------------------------------------------- #


def test_la_biblioteca_tiene_catorce_predicados():
    assert len(LIBRARY) == 14


def test_todo_predicado_declara_señal_y_severidad():
    for p in LIBRARY.values():
        assert p.severity is not None
        assert p.signal_code(**{k: _muestra(s) for k, s in p.params.items()})


def test_solo_dos_predicados_son_de_context():
    de_context = {n for n, p in LIBRARY.items() if p.is_context()}
    assert de_context == {"merchant_blacklisted", "amount_over_absolute"}


def test_ningun_predicado_pide_insumos_fuera_del_catalogo():
    validos = set(CONTEXT_INPUTS) | {"profile", "history_customer", "history_device"}
    for p in LIBRARY.values():
        assert p.requires <= validos


def test_sin_perfil_siguen_disponibles_los_predicados_de_historial(tx):
    """Un cliente sin perfil no apaga el historial: son insumos distintos.

    Las ~96 transacciones sin perfil del dataset dependen de esto. Lo que queda
    fuera es lo que **contrasta** contra el perfil, no lo que mira la secuencia:
    un dispositivo en ráfaga es sospechoso exista o no el perfil.
    """
    disponibles = ctx(tx()).available
    evaluables = {n for n, p in LIBRARY.items() if p.requires <= disponibles}

    assert "merchant_blacklisted" in evaluables
    assert "count_in_window" in evaluables
    assert "distinct_country_in_window" in evaluables
    assert "amount_over_avg_multiple" not in evaluables
    assert "outside_usual_hours" not in evaluables


def test_sin_perfil_el_motor_evalua_mas_politicas_que_el_etiquetador(tx, catalogo):
    """Divergencia conocida y latente. Hoy no produce ni un caso.

    `build_ground_truth.py` hace `continue` tras evaluar FP-07 cuando el perfil
    falta, así que nunca etiqueta FP-03 ni FP-05 para esas transacciones. El
    motor sí las evalúa, porque ninguna de las dos necesita el perfil.

    Medido sobre el dataset: **cero** transacciones sin perfil disparan FP-03 o
    FP-05, así que `check_policies.py` da 0 discrepancias. Pero la coincidencia
    es del dato, no del diseño: si el dataset cambia, el gate va a marcar falsos
    positivos que no son errores del motor.

    Este test existe para que la divergencia esté escrita en algún lado que se
    ejecute, y no sólo en un acta.
    """
    disponibles = ctx(tx()).available
    evaluables = {
        p.policy_id
        for p in catalogo.policies
        if p.evaluable and p.requires <= disponibles
    }
    assert evaluables == {"FP-03", "FP-05", "FP-07"}


def _muestra(spec):
    if spec.kind == "choice":
        return spec.choices[0]
    return int(spec.minimum or 1) if spec.kind == "integer" else float(spec.minimum or 1.0)
