"""Tests del scoring determinístico (tarea 2.5).

Verifica las dos propiedades que el contrato exige (contrato §2.5):

- `risk_score` es **monótona** en las severidades.
- `base_confidence` tiene **forma de U**: máxima en extremos limpios, mínima en
  evidencia contradictoria, y un factor reductor cuando hay agentes degradados.
"""

from src.domain.policies import PolicySignal
from src.domain.scoring import SCORING_VERSION, base_confidence, risk_score
from src.enums import Severity


def _senal(severity: Severity) -> PolicySignal:
    return PolicySignal(code="X", description="x", severity=severity)


def test_riesgo_monotono_en_severidades():
    base = [_senal(Severity.LOW)]
    con_media = base + [_senal(Severity.MEDIUM)]
    con_alta = con_media + [_senal(Severity.HIGH)]
    assert risk_score(base) < risk_score(con_media) < risk_score(con_alta)


def test_riesgo_cero_sin_senales():
    assert risk_score([]) == 0.0


def test_riesgo_saturado_a_uno():
    muchas = [_senal(Severity.HIGH) for _ in range(10)]
    assert risk_score(muchas) == 1.0


def test_riesgo_en_rango():
    assert 0.0 <= risk_score([_senal(Severity.HIGH)]) <= 1.0


def test_confianza_forma_de_u():
    assert base_confidence(0.0) > base_confidence(0.25)
    assert base_confidence(0.25) > base_confidence(0.5)
    assert base_confidence(0.75) > base_confidence(0.5)
    assert base_confidence(1.0) > base_confidence(0.75)
    # máxima en ambos extremos
    assert base_confidence(0.0) >= base_confidence(0.75)
    assert base_confidence(1.0) >= base_confidence(0.25)


def test_confianza_reducida_por_degradacion():
    r = 0.3
    assert base_confidence(r, degraded=True) < base_confidence(r)


def test_confianza_en_rango():
    for r in (0.0, 0.25, 0.5, 0.75, 1.0):
        assert 0.0 <= base_confidence(r) <= 1.0
        assert 0.0 <= base_confidence(r, degraded=True) <= 1.0


def test_scoring_version_presente():
    assert SCORING_VERSION  # la versión de la fórmula queda identificada
