"""Nodos de debate: el cableado del try/except propio sobre el `Narrator`.

Sin red: prueban que el nodo arme el prompt con la evidencia ya consolidada
del estado, que un fallo del proveedor caiga al respaldo declarado -no a
cadena vacía, que el esquema no permite- y que ese respaldo quede marcado en
`agent_errors` para que la auditoría lo muestre.
"""

from dataclasses import dataclass

from multiagent_fraud_detection.debate.pro_customer import (
    fallback_argument as respaldo_cliente,
)
from multiagent_fraud_detection.debate.pro_fraud import (
    fallback_argument as respaldo_fraude,
)
from multiagent_fraud_detection.enums import Severity
from multiagent_fraud_detection.explain.narrator import FakeNarrator
from multiagent_fraud_detection.graph.nodes import (
    PRO_CUSTOMER,
    PRO_FRAUD,
    debate_pro_customer,
    debate_pro_fraud,
)
from multiagent_fraud_detection.graph.state import WorkingSignal


def señal(code="DEVICE_VELOCITY"):
    return WorkingSignal(
        code=code,
        description=f"detalle de {code}",
        severity=Severity.MEDIUM,
        emitted_by="behavioral_pattern",
    )


def estado(**extra):
    base = {"evidence": [señal()], "policies": ["FP-03"], "risk_score": 0.6}
    return {**base, **extra}


@dataclass
class FakeRuntime:
    context: object


@dataclass
class FakeGraphContext:
    narrator: object


class NarradorRoto:
    def narrate(self, system, user):
        raise ConnectionError("proveedor caído")


class TestDebateProFraud:
    async def test_camino_feliz_usa_el_narrador(self):
        rt = FakeRuntime(FakeGraphContext(FakeNarrator("[argumento pro-fraude]")))
        salida = await debate_pro_fraud(estado(), rt)

        assert salida["pro_fraud_argument"] == "[argumento pro-fraude]"
        assert salida["agent_route"] == [PRO_FRAUD]
        assert "agent_errors" not in salida

    async def test_proveedor_caido_cae_al_respaldo_declarado(self):
        rt = FakeRuntime(FakeGraphContext(NarradorRoto()))
        salida = await debate_pro_fraud(estado(), rt)

        assert salida["pro_fraud_argument"] == respaldo_fraude()
        assert salida["agent_errors"][0].agent == PRO_FRAUD
        assert salida["agent_errors"][0].error_type == "ConnectionError"

    async def test_estado_sin_evidencia_consolidada_no_revienta(self):
        """No debería ocurrir -el debate corre después de Evidence
        Aggregation- pero el nodo no puede asumirlo: `.get` con default es lo
        que evita un `KeyError` si el orden del grafo cambiara."""
        rt = FakeRuntime(FakeGraphContext(FakeNarrator()))
        salida = await debate_pro_fraud({}, rt)
        assert salida["agent_route"] == [PRO_FRAUD]


class TestDebateProCustomer:
    async def test_camino_feliz_usa_el_narrador(self):
        rt = FakeRuntime(FakeGraphContext(FakeNarrator("[argumento pro-cliente]")))
        salida = await debate_pro_customer(estado(), rt)

        assert salida["pro_customer_argument"] == "[argumento pro-cliente]"
        assert salida["agent_route"] == [PRO_CUSTOMER]
        assert "agent_errors" not in salida

    async def test_proveedor_caido_cae_al_respaldo_declarado(self):
        rt = FakeRuntime(FakeGraphContext(NarradorRoto()))
        salida = await debate_pro_customer(estado(), rt)

        assert salida["pro_customer_argument"] == respaldo_cliente()
        assert salida["agent_errors"][0].agent == PRO_CUSTOMER
        assert salida["agent_errors"][0].error_type == "ConnectionError"
