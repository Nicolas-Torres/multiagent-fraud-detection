"""El gate: el motor reproduce el ground truth sobre las 7 000 transacciones.

Es el mismo cálculo que `scripts/check_policies.py` —que se conserva porque
imprime el reporte por política que alimenta el entregable 7—, acá expresado como
test para que `pytest` sea un solo comando en CI.

Corre en poco más de un segundo porque no toca base, red ni LLM. Esa es la razón
por la que la capa de reglas se diseñó sin I/O: un gate que tarda vuelve a ser
opcional en la práctica.

**Lo que prueba**: que dos implementaciones independientes de las mismas once
políticas —el etiquetador escrito a mano con pandas y el intérprete leyendo las
vinculaciones— coinciden fila por fila.

**Lo que no prueba**: que las consultas de historial respeten el `as_of`. Acá el
historial se arma en memoria. Eso lo cubre el smoke contra la base sembrada.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from _dataset import BLACKLIST, leer_ground_truth, leer_perfiles, leer_transacciones
from check_policies import evaluar_todo


@pytest.fixture(scope="module")
def corrida(catalogo):
    """Una sola evaluación del dataset completo, compartida por los tests."""
    perfiles = {p.customer_id: p for p in leer_perfiles()}
    obtenido = evaluar_todo(
        catalogo,
        perfiles,
        leer_transacciones(),
        frozenset(m.merchant_id for m in BLACKLIST),
    )
    return obtenido, leer_ground_truth()


def test_el_motor_reproduce_las_politicas_esperadas(corrida):
    obtenido, esperado = corrida
    fallan = [
        tid for tid, esp in esperado.items() if obtenido[tid][0] != esp["policies"]
    ]
    assert fallan == [], f"{len(fallan)} transacciones con políticas distintas"


def test_la_precedencia_reproduce_la_decision_esperada(corrida):
    """Si el Arbiter resolviera los conflictos con otra regla, la comparación
    contra el ground truth sería injusta."""
    obtenido, esperado = corrida
    fallan = [
        tid for tid, esp in esperado.items() if obtenido[tid][1] != esp["decision"]
    ]
    assert fallan == [], f"{len(fallan)} transacciones con decisión distinta"


def test_ninguna_politica_queda_sin_ejercitar(corrida, catalogo):
    """Una política que nunca dispara en 7 000 filas no está probada por el gate.

    Hoy las diez evaluables tienen positivos. Si mañana una queda en cero, el
    gate seguiría en verde midiendo nueve.
    """
    obtenido, _ = corrida
    disparadas = {p for pol, _, _ in obtenido.values() for p in pol}
    evaluables = {p.policy_id for p in catalogo.policies if p.evaluable}
    assert evaluables - disparadas == set()


def test_toda_señal_del_catalogo_aparece_al_menos_una_vez(corrida, catalogo):
    """Lo mismo para el vocabulario de señales que el entregable 6 vigila."""
    obtenido, _ = corrida
    emitidas = {s.code for _, _, sigs in obtenido.values() for s in sigs}
    declaradas = {c for p in catalogo.policies for c in p.signals}
    assert declaradas - emitidas == set()
