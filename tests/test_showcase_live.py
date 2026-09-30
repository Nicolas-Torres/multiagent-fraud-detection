"""Cada caso de la vitrina, re-ejecutado en vivo, llega al mismo piso que su
fila del dataset (incidente 0008, T-2579).

"Volver a ejecutar" sufija dispositivo y comercio (`transaccionParaCorridaEnVivo`
en `liveScenarios.ts`). T-2579 aprobaba con país extranjero y dispositivo
habitual; en vivo el dispositivo pasaba a ser nuevo y FP-02 lo escalaba: la
vitrina decía "Aprobado" y la corrida, "Derivado al analista". Sin red ni base:
el motor determinístico sobre el catálogo en archivo y el dataset del repo.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from _dataset import BLACKLIST, leer_ground_truth, leer_perfiles, leer_transacciones
from check_policies import elegir_fuente

from multiagent_fraud_detection.api.showcase import CASOS_VITRINA
from multiagent_fraud_detection.domain.catalog import Owner, build_catalog
from multiagent_fraud_detection.domain.engine import evaluate, prescribed_action
from multiagent_fraud_detection.domain.predicates import EvalContext

CATALOGO = build_catalog(elegir_fuente("file").fetch())
PERFILES = {p.customer_id: p for p in leer_perfiles()}
TRANSACCIONES = {t.transaction_id: t for t in leer_transacciones()}
GROUND_TRUTH = leer_ground_truth()
LISTA_NEGRA = frozenset(m.merchant_id for m in BLACKLIST)


def _accion(transaccion, historial) -> str:
    ctx = EvalContext(
        transaction=transaccion,
        profile=PERFILES.get(transaccion.customer_id),
        history_customer=tuple(historial),
        history_device=(),
        blacklist=LISTA_NEGRA,
        indicators={},
    )
    evidencia = (
        evaluate(CATALOGO, Owner.CONTEXT, ctx)
        .merge(evaluate(CATALOGO, Owner.BEHAVIORAL, ctx))
        .merge(evaluate(CATALOGO, Owner.THREAT_INTEL, ctx))
    )
    return prescribed_action(CATALOGO, evidencia.matched_policies).value


@pytest.mark.parametrize("transaction_id", list(CASOS_VITRINA))
def test_la_corrida_en_vivo_llega_al_mismo_piso_que_la_vitrina(transaction_id):
    original = TRANSACCIONES[transaction_id]
    # Como en producción: la fila original ya está sembrada, y cada visitante
    # que re-ejecuta suma una corrida más del mismo cliente al historial.
    historial = [original]
    for token in range(1, 4):
        en_vivo = original.model_copy(
            update={
                "transaction_id": f"LIVE-vitrina-{token}",
                "device_id": f"{original.device_id}-{token}",
                "merchant_id": f"{original.merchant_id}-{token}",
            }
        )
        assert _accion(en_vivo, historial) == GROUND_TRUTH[transaction_id]["decision"]
        historial.append(en_vivo)
