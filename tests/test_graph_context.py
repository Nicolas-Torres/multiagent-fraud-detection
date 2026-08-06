"""`GraphContext` completo y la caché de indicadores.

El acta 06 §6.3 advirtió: `pytest` dio 161 verdes con un `GraphContext` al que
le faltaban tres campos, porque la suite corre sin red y sin base y ningún
test arma el contexto real —sólo dobles que duplican un subconjunto de
campos—. El error apareció recién en el smoke.

`test_graph_context_completo_expone_indicators` cierra el hueco para este
campo: arma el `GraphContext` de verdad, con sus fábricas por defecto, en vez
de un `FakeGraphContext` que sólo declara lo que el nodo de turno necesita. El
resto del archivo prueba la caché que ese campo expone, con el mismo criterio
que ya usan las cuatro pruebas de `BlacklistCache`.
"""

from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from multiagent_fraud_detection.db.repositories.threat_indicator import (
    Indicator,
    IndicatorCache,
    active_indicators,
)
from multiagent_fraud_detection.enums import IndicatorType
from multiagent_fraud_detection.graph.context import GraphContext

AHORA = datetime(2026, 1, 1, tzinfo=timezone.utc)


# --------------------------------------------------------------------------- #
# Dobles
# --------------------------------------------------------------------------- #


def _fila(
    indicator_type: IndicatorType = IndicatorType.ISSUER,
    value: str = "CABK",
    dias_atras: int = 0,
    url: str = "https://sbs.gob.pe/alertas/x",
    resumen: str = "SBS - Alerta de fraude",
):
    """Una fila de `threat_indicators` tal como la devuelve SQLAlchemy.

    `active_indicators` lee estos atributos directo, sin `getattr` defensivo
    —a diferencia de `_extraer` en `intel/searcher.py`—: son filas propias de
    la base, no contenido de un proveedor externo.
    """
    return SimpleNamespace(
        indicator_type=indicator_type,
        value=value,
        observed_at=AHORA - timedelta(days=dias_atras),
        retrieved_at=AHORA,
        source_url=url,
        summary=resumen,
    )


class FakeSessionFactory:
    """Cuenta cuántas veces se abrió una sesión. Molde de la de
    `test_node_context.py`, con filas de `threat_indicators` en vez de
    `merchant_blacklist`.

    Sirve dos roles: es la *fábrica* (`session_factory()` abre una sesión) y
    es la *sesión* misma (`self.scalars(...)`) — el objeto que
    `_sesion()` produce es `self`.
    """

    def __init__(self, filas=()):
        self.filas = list(filas)
        self.aperturas = 0

    def __call__(self):
        self.aperturas += 1
        factory = self

        @asynccontextmanager
        async def _sesion():
            yield factory

        return _sesion()

    async def scalars(self, _stmt):
        return _Scalars(self.filas)


@dataclass
class _Scalars:
    valores: list

    def all(self):
        return list(self.valores)


# --------------------------------------------------------------------------- #
# `active_indicators`: la indexación
# --------------------------------------------------------------------------- #


class TestActiveIndicators:
    async def test_indexa_por_tipo_y_valor(self):
        factory = FakeSessionFactory(
            [_fila(value="CABK"), _fila(IndicatorType.MERCHANT, value="CABK")]
        )

        async with factory() as session:
            indice = await active_indicators(session)

        # Mismo `value`, distinto `indicator_type`: son dos claves, no una.
        # Un índice que sólo mirara `value` mezclaría un emisor con un
        # comercio que compartiera código por coincidencia.
        assert set(indice) == {
            (IndicatorType.ISSUER, "CABK"),
            (IndicatorType.MERCHANT, "CABK"),
        }

    async def test_conserva_el_orden_de_la_consulta(self):
        """El `ORDER BY observed_at DESC` lo cumple Postgres, no este código:
        un doble sin base no puede probar que la base ordena. Lo que sí puede
        probar es que `active_indicators` no reordena ni invierte lo que la
        consulta ya entregó ordenado.
        """
        nueva = _fila(dias_atras=1)
        vieja = _fila(dias_atras=10)
        factory = FakeSessionFactory([nueva, vieja])  # ya en el orden de la query

        async with factory() as session:
            indice = await active_indicators(session)

        obtenidos = indice[(IndicatorType.ISSUER, "CABK")]
        assert [o.observed_at for o in obtenidos] == [
            nueva.observed_at,
            vieja.observed_at,
        ]

    async def test_valores_se_copian_a_indicator(self):
        factory = FakeSessionFactory([_fila()])

        async with factory() as session:
            indice = await active_indicators(session)

        [obtenido] = indice[(IndicatorType.ISSUER, "CABK")]
        assert obtenido == Indicator(
            indicator_type=IndicatorType.ISSUER,
            value="CABK",
            observed_at=AHORA,
            retrieved_at=AHORA,
            source_url="https://sbs.gob.pe/alertas/x",
            summary="SBS - Alerta de fraude",
        )

    async def test_sin_filas_da_indice_vacio(self):
        factory = FakeSessionFactory([])

        async with factory() as session:
            indice = await active_indicators(session)

        assert indice == {}


# --------------------------------------------------------------------------- #
# `IndicatorCache`: mismo criterio que `BlacklistCache`
# --------------------------------------------------------------------------- #


class TestIndicatorCache:
    async def test_la_cache_consulta_una_sola_vez(self):
        factory = FakeSessionFactory([_fila()])
        cache = IndicatorCache(ttl_seconds=1000)

        for _ in range(5):
            indice = await cache.get(factory)
            assert (IndicatorType.ISSUER, "CABK") in indice

        assert factory.aperturas == 1

    async def test_invalidate_fuerza_la_relectura(self):
        factory = FakeSessionFactory([_fila()])
        cache = IndicatorCache(ttl_seconds=1000)

        await cache.get(factory)
        cache.invalidate()
        await cache.get(factory)

        assert factory.aperturas == 2

    async def test_ttl_cero_desactiva_la_cache(self):
        factory = FakeSessionFactory([_fila()])
        cache = IndicatorCache(ttl_seconds=0)

        await cache.get(factory)
        await cache.get(factory)

        assert factory.aperturas == 2

    async def test_la_cache_vence_cuando_pasa_el_ttl(self):
        factory = FakeSessionFactory([_fila()])
        cache = IndicatorCache(ttl_seconds=60)

        await cache.get(factory)
        assert factory.aperturas == 1

        cache._cargado_en -= 61
        await cache.get(factory)
        assert factory.aperturas == 2


# --------------------------------------------------------------------------- #
# El contexto completo — el hueco que el acta 06 §6.3 dejó abierto
# --------------------------------------------------------------------------- #


def test_graph_context_completo_expone_indicators():
    """El `GraphContext` real, no un `FakeGraphContext` que declara un
    subconjunto de campos a mano. Si `indicators` desapareciera del
    dataclass, o dejara de tener un `default_factory`, esto rompe acá — antes
    del smoke, no después.
    """
    contexto = GraphContext(session_factory=FakeSessionFactory())

    assert isinstance(contexto.indicators, IndicatorCache)
