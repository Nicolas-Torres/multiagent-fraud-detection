"""Nodo Behavioral Pattern.

La lógica de las nueve políticas ya está probada sobre las 7 000 transacciones
sin base. Lo que se prueba acá es el **cableado**, y en particular las dos cosas
que solo pueden salir mal al conectar el dominio con Postgres:

1. Que el `as_of` sea el timestamp de la transacción y no `now()`.
2. Que la transacción bajo análisis no se cuente dos veces en su propia ventana.

Las dos fallan hacia arriba —más recall del real— y ninguna se nota en
producción. Por eso van con doble de sesión que **captura los argumentos** en vez
de con una base real: acá interesa qué se consultó, no qué devolvió el motor SQL.
"""

from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from multiagent_fraud_detection.db.repositories.merchant_blacklist import BlacklistCache
from multiagent_fraud_detection.graph.nodes import BEHAVIORAL, behavioral_pattern

from conftest import utc


@dataclass
class Espia:
    """Registra con qué argumentos se llamó a cada repositorio."""

    perfil: object = None
    historial_cliente: list = field(default_factory=list)
    historial_dispositivo: list = field(default_factory=list)
    llamadas: dict = field(default_factory=dict)


@pytest.fixture
def espia_y_runtime(catalogo, monkeypatch):
    espia = Espia()

    async def fake_profile_for(session, *, customer_id):
        espia.llamadas["profile"] = {"customer_id": customer_id}
        return espia.perfil

    async def fake_history_customer(session, **kw):
        espia.llamadas["history_customer"] = kw
        return espia.historial_cliente

    async def fake_history_device(session, **kw):
        espia.llamadas["history_device"] = kw
        return espia.historial_dispositivo

    import multiagent_fraud_detection.graph.nodes as nodes_mod

    monkeypatch.setattr(nodes_mod, "profile_for", fake_profile_for)
    monkeypatch.setattr(nodes_mod, "history_for_customer", fake_history_customer)
    monkeypatch.setattr(nodes_mod, "history_for_device", fake_history_device)

    @asynccontextmanager
    async def _sesion():
        yield object()

    @dataclass
    class Ctx:
        session_factory: object
        catalog: object
        blacklist: BlacklistCache

    @dataclass
    class Rt:
        context: object

    return espia, Rt(Ctx(lambda: _sesion(), catalogo, BlacklistCache()))


def codigos(salida):
    return {s.code for s in salida["signals"]}


# --------------------------------------------------------------------------- #
# El invariante as-of
# --------------------------------------------------------------------------- #


async def test_el_as_of_es_el_timestamp_de_la_transaccion_no_now(tx, perfil, espia_y_runtime):
    """`now()` funciona en producción y solo miente en evaluación.

    En producción el futuro no está en la tabla, así que el bug es invisible. En
    evaluación el dataset se carga completo: el agente vería ráfagas enteras
    desde su primera transacción e inflaría su propio recall. El harness
    certificaría un sistema que no funciona.
    """
    espia, rt = espia_y_runtime
    espia.perfil = perfil
    momento = utc(2025, 6, 1, 12, 0)  # muy en el pasado

    await behavioral_pattern({"transaction": tx(timestamp=momento)}, rt)

    assert espia.llamadas["history_customer"]["as_of"] == momento
    assert espia.llamadas["history_device"]["as_of"] == momento
    assert momento < datetime.now(timezone.utc)  # no es `now()`, es el pasado


async def test_la_transaccion_bajo_analisis_se_excluye_del_historial(
    tx, perfil, espia_y_runtime
):
    """El repositorio filtra con `<=`, así que la transacción cae en su propia
    ventana; los predicados hacen `len(previas) + 1`. Sin exclusión se contaría
    dos veces y FP-03 dispararía con tres previas en vez de cuatro."""
    espia, rt = espia_y_runtime
    espia.perfil = perfil

    await behavioral_pattern({"transaction": tx(transaction_id="T-42")}, rt)

    assert espia.llamadas["history_customer"]["exclude_transaction_id"] == "T-42"
    assert espia.llamadas["history_device"]["exclude_transaction_id"] == "T-42"


async def test_consulta_los_dos_ejes_con_las_claves_correctas(tx, perfil, espia_y_runtime):
    """El eje dispositivo no filtra por cliente: es la razón de ser de FP-03."""
    espia, rt = espia_y_runtime
    espia.perfil = perfil

    await behavioral_pattern(
        {"transaction": tx(customer_id="CU-7", device_id="D-9")}, rt
    )

    assert espia.llamadas["history_customer"]["customer_id"] == "CU-7"
    assert espia.llamadas["history_device"]["device_id"] == "D-9"
    assert "customer_id" not in espia.llamadas["history_device"]


# --------------------------------------------------------------------------- #
# Cliente sin perfil
# --------------------------------------------------------------------------- #


async def test_sin_perfil_emite_señal_y_no_explota(tx, espia_y_runtime):
    espia, rt = espia_y_runtime
    espia.perfil = None

    salida = await behavioral_pattern({"transaction": tx()}, rt)

    assert salida["customer_snapshot"] is None
    assert "NO_CUSTOMER_PROFILE" in codigos(salida)
    assert salida["matched_policies"] == []


async def test_la_señal_sin_perfil_dice_cuantas_politicas_quedaron_fuera(
    tx, espia_y_runtime
):
    """`customer_snapshot=None` sería indistinguible de "el nodo no corrió"."""
    espia, rt = espia_y_runtime
    espia.perfil = None

    salida = await behavioral_pattern({"transaction": tx(customer_id="CU-404")}, rt)
    señal = next(s for s in salida["signals"] if s.code == "NO_CUSTOMER_PROFILE")

    assert "CU-404" in señal.description
    # 9 evaluables por Behavioral, menos FP-03 y FP-05 que no necesitan perfil.
    assert "7 politicas" in señal.description


async def test_sin_perfil_las_politicas_de_secuencia_siguen_corriendo(
    tx, espia_y_runtime
):
    """FP-03 y FP-05 no dependen del perfil: una ráfaga de dispositivo es
    sospechosa exista o no el cliente."""
    espia, rt = espia_y_runtime
    espia.perfil = None
    t = utc(2026, 3, 10, 15, 0)
    espia.historial_dispositivo = [
        tx(transaction_id=f"T-{i}", timestamp=t - timedelta(minutes=i)) for i in (1, 2, 3)
    ]

    salida = await behavioral_pattern({"transaction": tx(timestamp=t)}, rt)

    assert salida["matched_policies"] == ["FP-03"]


# --------------------------------------------------------------------------- #
# Con perfil
# --------------------------------------------------------------------------- #


async def test_el_perfil_viaja_al_estado_como_snapshot(tx, perfil, espia_y_runtime):
    """Congela lo mutable: el caso guarda el perfil que se usó para decidir."""
    espia, rt = espia_y_runtime
    espia.perfil = perfil

    salida = await behavioral_pattern({"transaction": tx()}, rt)

    assert salida["customer_snapshot"] is perfil
    assert "NO_CUSTOMER_PROFILE" not in codigos(salida)


async def test_monto_atipico_fuera_de_horario_dispara_fp01(tx, perfil, espia_y_runtime):
    espia, rt = espia_y_runtime
    espia.perfil = perfil

    salida = await behavioral_pattern(
        {"transaction": tx(amount=Decimal("4000.00"), timestamp=utc(2026, 3, 11, 2, 0))},
        rt,
    )

    assert "FP-01" in salida["matched_policies"]
    assert {"AMOUNT_OVER_USUAL_AVG", "OUTSIDE_USUAL_HOURS"} <= codigos(salida)


async def test_una_señal_cierta_se_emite_aunque_la_politica_no_complete(
    tx, perfil, espia_y_runtime
):
    espia, rt = espia_y_runtime
    espia.perfil = perfil

    salida = await behavioral_pattern(
        {"transaction": tx(amount=Decimal("4000.00"), timestamp=utc(2026, 3, 10, 15, 0))},
        rt,
    )

    assert "FP-01" not in salida["matched_policies"]
    assert "AMOUNT_OVER_USUAL_AVG" in codigos(salida)


async def test_las_señales_llevan_procedencia(tx, perfil, espia_y_runtime):
    espia, rt = espia_y_runtime
    espia.perfil = perfil

    salida = await behavioral_pattern({"transaction": tx(country="ES")}, rt)

    assert salida["signals"]
    assert all(s.emitted_by == BEHAVIORAL for s in salida["signals"])


async def test_una_falla_de_base_se_convierte_en_evidencia(tx, catalogo):
    """Sin `@degrades`, esta excepción se llevaría puestos a Context y a Threat
    Intel del mismo superstep paralelo."""

    @dataclass
    class Ctx:
        session_factory: object
        catalog: object
        blacklist: BlacklistCache

    @dataclass
    class Rt:
        context: object

    def factory_rota():
        raise RuntimeError("Postgres caído")

    salida = await behavioral_pattern(
        {"transaction": tx()}, Rt(Ctx(factory_rota, catalogo, BlacklistCache()))
    )

    assert salida["agent_errors"][0].agent == BEHAVIORAL
    assert "signals" not in salida
