"""Nodo Transaction Context y la caché de la lista negra.

Sin Postgres: la sesión se sustituye por un doble que cuenta llamadas. Lo que se
prueba acá no es SQL —eso lo cubre el smoke contra la base sembrada— sino el
cableado: que el nodo traduzca del dominio al estado, que respete el contrato de
retorno de LangGraph, y que `@degrades` convierta una falla en evidencia.
"""

from contextlib import asynccontextmanager
from dataclasses import dataclass
from decimal import Decimal

import pytest

from multiagent_fraud_detection.db.repositories.merchant_blacklist import BlacklistCache
from multiagent_fraud_detection.graph.nodes import CONTEXT, transaction_context


# --------------------------------------------------------------------------- #
# Dobles
# --------------------------------------------------------------------------- #


class FakeSessionFactory:
    """Cuenta cuántas veces se abrió una sesión. Es lo único que interesa acá."""

    def __init__(self, merchants=("M-999",)):
        self.merchants = frozenset(merchants)
        self.aperturas = 0

    def __call__(self):
        self.aperturas += 1
        factory = self

        @asynccontextmanager
        async def _sesion():
            yield factory

        return _sesion()

    async def scalars(self, _stmt):
        return _Scalars(self.merchants)


@dataclass
class _Scalars:
    valores: frozenset

    def all(self):
        return list(self.valores)


@dataclass
class FakeRuntime:
    context: object


@dataclass
class FakeGraphContext:
    session_factory: object
    catalog: object
    blacklist: BlacklistCache


@pytest.fixture
def runtime(catalogo):
    factory = FakeSessionFactory()
    return FakeRuntime(
        FakeGraphContext(factory, catalogo, BlacklistCache(ttl_seconds=1000))
    ), factory


# --------------------------------------------------------------------------- #
# La caché
# --------------------------------------------------------------------------- #


async def test_la_cache_consulta_una_sola_vez():
    """7 000 transacciones no pueden ser 7 000 consultas para leer la misma lista."""
    factory = FakeSessionFactory()
    cache = BlacklistCache(ttl_seconds=1000)

    for _ in range(5):
        assert await cache.get(factory) == frozenset({"M-999"})

    assert factory.aperturas == 1


async def test_invalidate_fuerza_la_relectura():
    """La réplica que atiende un alta desde el dashboard debe verla al instante."""
    factory = FakeSessionFactory()
    cache = BlacklistCache(ttl_seconds=1000)

    await cache.get(factory)
    cache.invalidate()
    await cache.get(factory)

    assert factory.aperturas == 2


async def test_ttl_cero_desactiva_la_cache():
    """`ttl_seconds=0` significa "no cachear", en cualquier plataforma.

    Depende de `>=` en `vencida`: con `>` este test pasa en Linux —donde
    `monotonic()` avanza siempre— y falla en Windows, cuyo temporizador ronda
    los 15 ms y devuelve el mismo valor en dos llamadas seguidas. Verde en CI y
    rojo en la máquina de quien programa es la peor combinación posible.
    """
    factory = FakeSessionFactory()
    cache = BlacklistCache(ttl_seconds=0)

    await cache.get(factory)
    await cache.get(factory)

    assert factory.aperturas == 2


async def test_la_cache_vence_cuando_pasa_el_ttl():
    """Obsolescencia acotada sin coordinación entre réplicas.

    Se fuerza el reloj hacia atrás en vez de dormir: un `sleep` real volvería
    lenta la suite y la haría dependiente del scheduler.
    """
    factory = FakeSessionFactory()
    cache = BlacklistCache(ttl_seconds=60)

    await cache.get(factory)
    assert factory.aperturas == 1

    cache._cargado_en -= 61
    await cache.get(factory)
    assert factory.aperturas == 2


# --------------------------------------------------------------------------- #
# El nodo
# --------------------------------------------------------------------------- #


async def test_comercio_en_lista_negra_sobre_el_umbral_dispara_fp07(tx, runtime):
    rt, _ = runtime
    estado = {"transaction": tx(amount=Decimal("5000.00"), merchant_id="M-999")}

    salida = await transaction_context(estado, rt)

    assert salida["matched_policies"] == ["FP-07"]
    assert {s.code for s in salida["signals"]} == {
        "MERCHANT_BLACKLISTED",
        "AMOUNT_OVER_ABSOLUTE",
    }


def _codigos(salida):
    return {s.code for s in salida["signals"]}


async def test_comercio_limpio_no_produce_nada(tx, runtime):
    rt, _ = runtime
    salida = await transaction_context({"transaction": tx(amount=Decimal("5000.00"))}, rt)

    assert salida["matched_policies"] == []
    assert salida["signals"] == []


async def test_monto_bajo_en_comercio_marcado_emite_la_señal_pero_no_la_politica(
    tx, runtime
):
    """La lista negra es cierta aunque FP-07 no complete: eso es evidencia."""
    rt, _ = runtime
    salida = await transaction_context(
        {"transaction": tx(amount=Decimal("10.00"), merchant_id="M-999")}, rt
    )

    assert salida["matched_policies"] == []
    assert _codigos(salida) == {"MERCHANT_BLACKLISTED"}


async def test_el_nodo_funciona_sin_perfil_del_cliente(tx, runtime):
    """El piso de evidencia: es el agente que sirve cuando el cliente no existe.

    El estado ni siquiera trae `customer_snapshot`, y aun así produce.
    """
    rt, _ = runtime
    salida = await transaction_context(
        {"transaction": tx(amount=Decimal("5000.00"), merchant_id="M-999")}, rt
    )
    assert salida["matched_policies"] == ["FP-07"]


async def test_el_nodo_se_anota_en_la_ruta(tx, runtime):
    rt, _ = runtime
    salida = await transaction_context({"transaction": tx()}, rt)
    assert salida["agent_route"] == [CONTEXT]


async def test_las_señales_llevan_procedencia(tx, runtime):
    """`emitted_by` lo pone el nodo: el dominio no conoce el grafo."""
    rt, _ = runtime
    salida = await transaction_context(
        {"transaction": tx(amount=Decimal("5000.00"), merchant_id="M-999")}, rt
    )
    assert all(s.emitted_by == CONTEXT for s in salida["signals"])


async def test_una_falla_se_convierte_en_evidencia_no_en_excepcion(tx, catalogo):
    """`@degrades` es obligatorio: un nodo que lanza en un superstep paralelo se
    lleva puestos los resultados de sus hermanos."""

    class FactoryRota:
        def __call__(self):
            raise RuntimeError("Postgres caído")

    rt = FakeRuntime(FakeGraphContext(FactoryRota(), catalogo, BlacklistCache()))
    salida = await transaction_context({"transaction": tx()}, rt)

    assert salida["agent_route"] == [CONTEXT]
    assert salida["agent_errors"][0].agent == CONTEXT
    assert salida["agent_errors"][0].error_type == "RuntimeError"
    assert "signals" not in salida
