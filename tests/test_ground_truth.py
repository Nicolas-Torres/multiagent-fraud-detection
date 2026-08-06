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
from check_policies import corpus_saturado, evaluar_todo

#: FP-10 está **activa y no medida** (ADR-0015): el ground truth no la contempla
#: y no se regenera, porque tocar la rama del generador correría el stream
#: aleatorio y cambiaría las 7 000 filas. No es un hueco de cobertura ni un
#: recall 0 — es una política implementada, citable, sin evidencia reproducible
#: contra la que medirla. Se nombra acá para que su ausencia sea una excepción
#: declarada y no un test que se fue debilitando.
SIN_GROUND_TRUTH = {"FP-10"}
SEÑALES_SIN_GROUND_TRUTH = {"ISSUER_UNDER_ALERT"}


@pytest.fixture(scope="module")
def corrida(catalogo):
    """Una sola evaluación del dataset completo, compartida por los tests.

    Con el mismo corpus saturado que usa `check_policies`: un indicador activo
    para cada emisor, fechado hoy. Es lo que convierte "FP-10 no disparó" en una
    afirmación sobre el dato —el desfase de ocho meses— y no sobre la
    configuración.
    """
    perfiles = {p.customer_id: p for p in leer_perfiles()}
    transacciones = leer_transacciones()
    obtenido = evaluar_todo(
        catalogo,
        perfiles,
        transacciones,
        frozenset(m.merchant_id for m in BLACKLIST),
        corpus_saturado(transacciones),
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

    Hoy las diez medibles tienen positivos. Si mañana una queda en cero, el gate
    seguiría en verde midiendo nueve.
    """
    obtenido, _ = corrida
    disparadas = {p for pol, _, _ in obtenido.values() for p in pol}
    evaluables = {p.policy_id for p in catalogo.policies if p.evaluable}
    assert evaluables - disparadas == SIN_GROUND_TRUTH


def test_fp10_no_dispara_ni_con_todos_los_emisores_bajo_alerta(corrida):
    """La invariante de ADR-0015, afirmada y no supuesta.

    El corpus de la corrida tiene un indicador para **cada** emisor del dataset,
    fechado hoy. Que FP-10 igual no dispare es una propiedad del dato: las 7 000
    transacciones son de diciembre de 2025 y la ventana de 24 h se resuelve
    *as-of* contra el `timestamp` del cargo, así que un indicador de hoy queda a
    ocho meses.

    El día que el dataset se regenere con fechas actuales, esto se pone rojo — que
    es exactamente lo que tiene que pasar.
    """
    obtenido, _ = corrida
    assert [tid for tid, (pol, _, _) in obtenido.items() if "FP-10" in pol] == []


def test_toda_señal_del_catalogo_aparece_al_menos_una_vez(corrida, catalogo):
    """Lo mismo para el vocabulario de señales que el entregable 6 vigila."""
    obtenido, _ = corrida
    emitidas = {s.code for _, _, sigs in obtenido.values() for s in sigs}
    declaradas = {c for p in catalogo.policies for c in p.signals}
    assert declaradas - emitidas == SEÑALES_SIN_GROUND_TRUTH
