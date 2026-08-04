"""Tests unitarios de las políticas del catálogo (tarea 2.4).

Cada test usa fixtures explícitos; ninguno toca la base. Los códigos de señal
esperados se fijan aquí para que el harness y los agentes compartan el
contrato de evidencia.
"""

from tests.conftest import historial, perfil, tx

from src.domain import policies


def test_fp01_monto_y_horario_fuera_de_rango():
    p = perfil(usual_amount_avg="1000.00", usual_hours="08-20")
    # 3x = 3000; 3500 > 3000 y 01:00 Lima cae fuera de 08-20
    t = tx(amount="3500.00", timestamp="2025-12-17T06:00:00+00:00")
    senal = policies.fp01(t, p)
    assert senal is not None
    assert senal.code == "AMOUNT_OUT_OF_RANGE"


def test_fp01_no_dispara_dentro_de_ventana():
    p = perfil(usual_amount_avg="1000.00", usual_hours="08-20")
    # 18:45 Lima está dentro de 08-20
    t = tx(amount="3500.00", timestamp="2025-12-17T23:45:00+00:00")
    assert policies.fp01(t, p) is None


def test_fp01_no_dispara_sin_monto_alto():
    p = perfil(usual_amount_avg="1000.00", usual_hours="08-20")
    t = tx(amount="2000.00", timestamp="2025-12-17T06:00:00+00:00")
    assert policies.fp01(t, p) is None


def test_fp02_internacional_y_dispositivo_nuevo():
    p = perfil(usual_countries="PE", usual_devices="D-01")
    t = tx(country="ES", device_id="D-99")
    senal = policies.fp02(t, p)
    assert senal is not None
    assert senal.code == "FOREIGN_NEW_DEVICE"


def test_fp02_no_dispara_si_solo_el_pais_es_nuevo():
    p = perfil(usual_countries="PE", usual_devices="D-01")
    t = tx(country="ES", device_id="D-01")
    assert policies.fp02(t, p) is None


def test_fp02_lista_vacia_significa_todo_nuevo():
    p = perfil(usual_countries="", usual_devices="")
    t = tx(country="ES", device_id="D-01")
    senal = policies.fp02(t, p)
    assert senal is not None
    assert senal.code == "FOREIGN_NEW_DEVICE"


def test_fp03_velocity_mas_de_tres_en_cinco_minutos():
    t = tx(timestamp="2025-12-17T10:00:00+00:00")
    previas = historial([
        tx(transaction_id="P1", device_id="D-01", timestamp="2025-12-17T09:56:00+00:00"),
        tx(transaction_id="P2", device_id="D-01", timestamp="2025-12-17T09:57:00+00:00"),
        tx(transaction_id="P3", device_id="D-01", timestamp="2025-12-17T09:58:00+00:00"),
    ])
    senal = policies.fp03(t, previas)
    assert senal is not None
    assert senal.code == "DEVICE_VELOCITY"


def test_fp03_no_dispara_con_tres():
    t = tx(timestamp="2025-12-17T10:00:00+00:00")
    previas = historial([
        tx(transaction_id="P1", device_id="D-01", timestamp="2025-12-17T09:56:00+00:00"),
        tx(transaction_id="P2", device_id="D-01", timestamp="2025-12-17T09:57:00+00:00"),
    ])
    assert policies.fp03(t, previas) is None


def test_fp04_card_testing():
    p = perfil(currency="PEN", usual_amount_avg="1000.00")  # factor 3.7
    t = tx(amount="2500.00", timestamp="2025-12-17T10:00:00+00:00")
    previas = historial([
        tx(transaction_id="M1", amount="0.50", timestamp="2025-12-17T09:52:00+00:00"),
        tx(transaction_id="M2", amount="1.00", timestamp="2025-12-17T09:55:00+00:00"),
    ])
    senal = policies.fp04(t, p, previas)
    assert senal is not None
    assert senal.code == "CARD_TESTING"


def test_fp04_no_dispara_sin_dos_micro():
    p = perfil(currency="PEN", usual_amount_avg="1000.00")
    t = tx(amount="2500.00", timestamp="2025-12-17T10:00:00+00:00")
    previas = historial([
        tx(transaction_id="M1", amount="0.50", timestamp="2025-12-17T09:55:00+00:00"),
    ])
    assert policies.fp04(t, p, previas) is None


def test_fp05_geo_imposible():
    t = tx(country="ES", timestamp="2025-12-17T10:00:00+00:00")
    previas = historial([
        tx(transaction_id="P1", country="PE", timestamp="2025-12-17T09:00:00+00:00"),
    ])
    senal = policies.fp05(t, previas)
    assert senal is not None
    assert senal.code == "IMPOSSIBLE_GEO"


def test_fp05_no_dispara_mismo_pais():
    t = tx(country="PE", timestamp="2025-12-17T10:00:00+00:00")
    previas = historial([
        tx(transaction_id="P1", country="PE", timestamp="2025-12-17T09:00:00+00:00"),
    ])
    assert policies.fp05(t, previas) is None


def test_fp06_canal_nuevo_con_monto_alto():
    p = perfil(usual_channel="web", usual_amount_avg="1000.00")
    t = tx(channel="mobile", amount="2500.00")
    senal = policies.fp06(t, p)
    assert senal is not None
    assert senal.code == "NEW_CHANNEL_HIGH_AMOUNT"


def test_fp06_no_dispara_sin_monto_alto():
    p = perfil(usual_channel="web", usual_amount_avg="1000.00")
    t = tx(channel="mobile", amount="1500.00")
    assert policies.fp06(t, p) is None


def test_fp07_merchant_en_lista_negra_sobre_umbral():
    # PEN factor 3.7 -> umbral 135 * 3.7 = 499.5
    t = tx(merchant_id="M-999", amount="2000.00", currency="PEN")
    senal = policies.fp07(t, "M-999", "PEN")
    assert senal is not None
    assert senal.code == "BLACKLISTED_MERCHANT"


def test_fp07_no_dispara_bajo_umbral():
    t = tx(merchant_id="M-999", amount="100.00", currency="PEN")
    assert policies.fp07(t, "M-999", "PEN") is None


def test_fp07_no_dispara_merchant_no_listado():
    t = tx(merchant_id="M-001", amount="2000.00", currency="PEN")
    assert policies.fp07(t, "M-001", "PEN") is None


def test_fp08_cuenta_nueva_monto_grande():
    p = perfil(account_creation_date="2025-12-01", segment="retail")
    # umbral segmento retail = 200 USD * 3.7 = 740 PEN; 5x = 3700
    t = tx(amount="4000.00", timestamp="2025-12-17T10:00:00+00:00")
    seg_avg_usd = {"retail": 200.0}
    senal = policies.fp08(t, p, seg_avg_usd)
    assert senal is not None
    assert senal.code == "NEW_ACCOUNT_HIGH_AMOUNT"


def test_fp08_no_dispara_cuenta_vieja():
    p = perfil(account_creation_date="2024-01-01", segment="retail")
    t = tx(amount="4000.00")
    senal = policies.fp08(t, p, {"retail": 200.0})
    assert senal is None


def test_fp09_cambio_de_perfil_y_transaccion_inmediata():
    # cambio 18:30 Lima = 23:30 UTC; tx 23:45 UTC -> 15 min
    p = perfil(last_profile_update="2025-12-17T18:30:00")
    t = tx(timestamp="2025-12-17T23:45:00+00:00")
    senal = policies.fp09(t, p)
    assert senal is not None
    assert senal.code == "PROFILE_CHANGE_IMMEDIATE_TX"


def test_fp09_no_dispara_fuera_de_ventana():
    p = perfil(last_profile_update="2025-12-16T18:30:00")
    t = tx(timestamp="2025-12-17T23:45:00+00:00")
    assert policies.fp09(t, p) is None


def test_fp11_smurfing():
    p = perfil(daily_limit="5000.00")
    t = tx(merchant_id="M-007", amount="1500.00", timestamp="2025-12-17T23:45:00+00:00")
    previas = historial([
        tx(transaction_id="P1", merchant_id="M-007", amount="2000.00", timestamp="2025-12-17T10:00:00+00:00"),
        tx(transaction_id="P2", merchant_id="M-007", amount="2000.00", timestamp="2025-12-17T11:00:00+00:00"),
    ])
    senal = policies.fp11(t, p, previas)
    assert senal is not None
    assert senal.code == "SMURFING"


def test_fp11_no_dispara_bajo_limite():
    p = perfil(daily_limit="5000.00")
    t = tx(merchant_id="M-007", amount="500.00", timestamp="2025-12-17T23:45:00+00:00")
    previas = historial([
        tx(transaction_id="P1", merchant_id="M-007", amount="2000.00", timestamp="2025-12-17T10:00:00+00:00"),
        tx(transaction_id="P2", merchant_id="M-007", amount="2000.00", timestamp="2025-12-17T11:00:00+00:00"),
    ])
    assert policies.fp11(t, p, previas) is None
