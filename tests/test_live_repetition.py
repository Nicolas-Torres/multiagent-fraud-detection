"""Repetir una fila ejecutable no cambia su veredicto (ADR-0030).

Cada corrida en vivo usa la fecha fija del escenario y queda guardada: el
historial del cliente crece con cada clic, de cualquier visitante, y no vence.
El sufijo de dispositivo y comercio (`transaccionParaCorridaEnVivo`) evita
FP-03 y FP-11; lo que este test cuida es que **ninguna otra** política que mire
el historial del cliente empiece a disparar por repetición.

Hasta ADR-0030 la espera global por escenario frenaba la repetición (12 por hora
como máximo). Sin ella, el único límite es el techo diario de la demo
(ADR-0025), así que se simula ese techo entero concentrado en un solo cliente.
Sin red ni base: el motor sobre el catálogo en archivo y el dataset del repo.
"""

import json
import re
import sys
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "scripts"))

from _dataset import BLACKLIST, leer_perfiles, leer_transacciones
from check_policies import elegir_fuente

from multiagent_fraud_detection.api.limites_demo import EJECUCIONES
from multiagent_fraud_detection.domain.catalog import Owner, build_catalog
from multiagent_fraud_detection.domain.engine import evaluate, prescribed_action
from multiagent_fraud_detection.domain.predicates import EvalContext
from multiagent_fraud_detection.schemas.transaction import TransactionIn

DATOS = RAIZ / "dashboard" / "src" / "data"
#: La misma ventana que `transaction_history.DEFAULT_WINDOW`, con `<=` inclusivo.
VENTANA = timedelta(hours=26)

CATALOGO = build_catalog(elegir_fuente("file").fetch())
PERFILES = {p.customer_id: p for p in leer_perfiles()}
LISTA_NEGRA = frozenset(m.merchant_id for m in BLACKLIST)
DATASET_POR_CLIENTE = defaultdict(list)
for _t in leer_transacciones():
    DATASET_POR_CLIENTE[_t.customer_id].append(_t)


def _escenarios_de_la_tabla() -> list[tuple[str, dict]]:
    """Los tres escritos a mano en `liveScenarios.ts`, leídos del fuente."""
    fuente = (DATOS / "liveScenarios.ts").read_text(encoding="utf-8")
    bloques = re.finditer(r"id: '([^']+)'.*?payload: \{(.*?)\n    \}", fuente, re.S)
    return [
        (f"tabla:{b.group(1)}", dict(re.findall(r"^\s+(\w+): '([^']*)'", b.group(2), re.M)))
        for b in bloques
    ]


def _filas_ejecutables() -> list[tuple[str, dict]]:
    filas = []
    for archivo, prefijo in (("showcase_cases.json", "vitrina"), ("diverse_scenarios.json", "diverso")):
        for e in json.loads((DATOS / archivo).read_text(encoding="utf-8")):
            filas.append((f"{prefijo}:{e['id']}", e["payload"]))
    return filas + _escenarios_de_la_tabla()


FILAS = _filas_ejecutables()
POR_CLIENTE: dict[str, list[tuple[str, dict]]] = defaultdict(list)
for _nombre, _payload in FILAS:
    POR_CLIENTE[_payload["customer_id"]].append((_nombre, _payload))


def _evaluar(tx: TransactionIn, historial) -> tuple[str, tuple[str, ...]]:
    ctx = EvalContext(
        transaction=tx,
        profile=PERFILES.get(tx.customer_id),
        history_customer=tuple(historial),
        history_device=(),  # el dispositivo sufijado nunca tiene historia
        blacklist=LISTA_NEGRA,
        indicators={},
    )
    evidencia = (
        evaluate(CATALOGO, Owner.CONTEXT, ctx)
        .merge(evaluate(CATALOGO, Owner.BEHAVIORAL, ctx))
        .merge(evaluate(CATALOGO, Owner.THREAT_INTEL, ctx))
    )
    politicas = tuple(sorted(evidencia.matched_policies))
    return prescribed_action(CATALOGO, politicas).value, politicas


def test_se_leen_todas_las_filas_ejecutables():
    """Sin esto, un cambio de formato en `liveScenarios.ts` dejaría al test de
    abajo recorriendo menos filas, en verde."""
    nombres = [n for n, _ in FILAS]
    assert sum(n.startswith("tabla:") for n in nombres) == 3
    assert sum(n.startswith("vitrina:") for n in nombres) == 5
    assert sum(n.startswith("diverso:") for n in nombres) >= 1


@pytest.mark.parametrize("cliente", sorted(POR_CLIENTE))
def test_repetir_no_cambia_el_veredicto(cliente):
    """Las filas de un mismo cliente se turnan, como pasaría con visitantes
    distintos: comparten historial (T-1809 y el escenario "challenge" son la
    misma transacción)."""
    filas = POR_CLIENTE[cliente]
    previas: list[TransactionIn] = []
    primera: dict[str, tuple[str, tuple[str, ...]]] = {}

    for n in range(EJECUCIONES.por_dia):
        nombre, payload = filas[n % len(filas)]
        tx = TransactionIn(
            **{
                **payload,
                "transaction_id": f"LIVE-repeticion-{n}",
                "device_id": f"{payload['device_id']}-{n}",
                "merchant_id": f"{payload['merchant_id']}-{n}",
            }
        )
        historial = [
            t
            for t in DATASET_POR_CLIENTE[cliente] + previas
            if tx.timestamp - VENTANA < t.timestamp <= tx.timestamp
        ]
        resultado = _evaluar(tx, historial)
        primera.setdefault(nombre, resultado)
        assert resultado == primera[nombre], f"{nombre}, corrida {n + 1}"
        previas.append(tx)
