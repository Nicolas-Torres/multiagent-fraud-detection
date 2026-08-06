"""Nodo External Threat Intel: lookup sobre el corpus congelado.

Sin Postgres y —a diferencia de las otras dos olas— **sin red por diseño**, no
por el doble: ADR-0014 sacó la búsqueda del grafo. Lo que se prueba acá es el
cableado: que el nodo traduzca del dominio al estado, que selle qué snapshot
consultó, y que `@degrades` convierta una falla en evidencia.
"""

from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta
from types import SimpleNamespace

import pytest

from multiagent_fraud_detection.db.repositories.threat_indicator import IndicatorCache
from multiagent_fraud_detection.enums import IndicatorType
from multiagent_fraud_detection.graph.nodes import THREAT_INTEL, external_threat_intel
from multiagent_fraud_detection.intel.snapshot import SNAPSHOT_VERSION

from conftest import utc

T0 = utc(2026, 3, 10, 15, 0)  # el default de la fábrica `tx`


# --------------------------------------------------------------------------- #
# Dobles
# --------------------------------------------------------------------------- #


def _fila(emisor="BCP", *, horas_atras=3, url="https://sbs.gob.pe/alertas/x"):
    return SimpleNamespace(
        indicator_type=IndicatorType.ISSUER,
        value=emisor,
        observed_at=T0 - timedelta(hours=horas_atras),
        retrieved_at=T0,
        source_url=url,
        summary="SBS - Alerta de fraude sobre el emisor",
    )


class FakeSessionFactory:
    def __init__(self, filas=()):
        self.filas = list(filas)

    def __call__(self):
        factory = self

        @asynccontextmanager
        async def _sesion():
            yield factory

        return _sesion()

    async def scalars(self, _stmt):
        return SimpleNamespace(all=lambda: list(self.filas))


@dataclass
class FakeRuntime:
    context: object


@dataclass
class FakeGraphContext:
    session_factory: object
    catalog: object
    indicators: IndicatorCache


def runtime_con(catalogo, filas=()):
    return FakeRuntime(
        FakeGraphContext(
            FakeSessionFactory(filas), catalogo, IndicatorCache(ttl_seconds=1000)
        )
    )


# --------------------------------------------------------------------------- #
# El nodo
# --------------------------------------------------------------------------- #


async def test_emisor_bajo_alerta_dispara_fp10_y_cita_la_fuente(tx, catalogo):
    """La cadena completa de ADR-0015, de la tabla al veredicto."""
    rt = runtime_con(catalogo, [_fila("BCP")])
    salida = await external_threat_intel({"transaction": tx(issuer_bank="BCP")}, rt)

    assert salida["matched_policies"] == ["FP-10"]
    assert [s.code for s in salida["signals"]] == ["ISSUER_UNDER_ALERT"]

    (cita,) = salida["citations_external"]
    assert str(cita.url) == "https://sbs.gob.pe/alertas/x"
    assert cita.summary == "SBS - Alerta de fraude sobre el emisor"
    assert cita.retrieved_at == T0


async def test_la_señal_se_atribuye_al_threat_intel_agent(tx, catalogo):
    """`emitted_by` es lo que el harness usa para atribuir falsos positivos.

    Si la evidencia externa la reportara Context —que es a donde la mandaría la
    partición binaria sin la precedencia de ADR-0015— este campo mentiría en el
    único lugar donde se lo consulta para medir.
    """
    rt = runtime_con(catalogo, [_fila("BCP")])
    salida = await external_threat_intel({"transaction": tx(issuer_bank="BCP")}, rt)

    assert all(s.emitted_by == THREAT_INTEL for s in salida["signals"])
    assert salida["agent_route"] == [THREAT_INTEL]


async def test_corpus_vacio_sella_igual_el_snapshot(tx, catalogo):
    """Consultar y no encontrar nada **es** haber consultado.

    La distinción importa porque `threat_intel_version` nulo significa *no se
    consultó snapshot*, no *no había alertas*. Confundirlas haría que un caso
    limpio y un caso con el nodo caído se vieran igual en la auditoría.
    """
    rt = runtime_con(catalogo, [])
    salida = await external_threat_intel({"transaction": tx(issuer_bank="BCP")}, rt)

    assert salida["threat_intel_version"] == SNAPSHOT_VERSION
    assert salida["matched_policies"] == []
    assert salida["signals"] == []
    assert salida["citations_external"] == []


async def test_alerta_fuera_de_la_ventana_no_dispara_ni_cita(tx, catalogo):
    rt = runtime_con(catalogo, [_fila("BCP", horas_atras=25)])
    salida = await external_threat_intel({"transaction": tx(issuer_bank="BCP")}, rt)

    assert salida["matched_policies"] == []
    assert salida["citations_external"] == []
    assert salida["threat_intel_version"] == SNAPSHOT_VERSION


async def test_alerta_sobre_otro_emisor_no_contamina(tx, catalogo):
    rt = runtime_con(catalogo, [_fila("BBVA")])
    salida = await external_threat_intel({"transaction": tx(issuer_bank="BCP")}, rt)

    assert salida["matched_policies"] == []
    assert salida["citations_external"] == []


async def test_transaccion_sin_emisor_no_es_error(tx, catalogo):
    """No toda transacción trae `issuer_bank`: la política no se cumple y ya."""
    rt = runtime_con(catalogo, [_fila("BCP")])
    salida = await external_threat_intel({"transaction": tx()}, rt)

    assert salida["matched_policies"] == []
    assert salida["threat_intel_version"] == SNAPSHOT_VERSION


async def test_no_escribe_discarded_sources(tx, catalogo):
    """ADR-0014: el allowlist gobierna la escritura, así que en runtime no hay
    nada que descartar — lo indebido nunca entró a la tabla."""
    rt = runtime_con(catalogo, [_fila("BCP")])
    salida = await external_threat_intel({"transaction": tx(issuer_bank="BCP")}, rt)

    assert "discarded_sources" not in salida


async def test_una_falla_se_convierte_en_evidencia_y_deja_el_sello_nulo(tx, catalogo):
    """`@degrades` sigue siendo obligatorio aunque el nodo ya no toque la red.

    Y la ausencia de `threat_intel_version` es lo que distingue *no se consultó*
    de *se consultó y no había nada*.
    """

    class FactoryRota:
        def __call__(self):
            raise RuntimeError("Postgres caído")

    rt = FakeRuntime(FakeGraphContext(FactoryRota(), catalogo, IndicatorCache()))
    salida = await external_threat_intel({"transaction": tx(issuer_bank="BCP")}, rt)

    assert salida["agent_route"] == [THREAT_INTEL]
    assert salida["agent_errors"][0].agent == THREAT_INTEL
    assert salida["agent_errors"][0].error_type == "RuntimeError"
    assert "threat_intel_version" not in salida
    assert "signals" not in salida
