"""Composición determinística del riesgo y la confianza base.

Dos números, dos formas (contrato §2.5):

- `risk_score` (sospecha) es **monótona** en las severidades: más señales o más
  graves nunca bajan el riesgo. Es la fórmula que vigila el drift, y **no** es
  ajustable por el Arbiter.
- `base_confidence` (seguridad) tiene **forma de U**: máxima en los extremos
  limpios (ninguna señal o señales contundentes) y mínima en el medio
  (evidencia contradictoria). Una función monótona no puede producir las dos.

`scoring_version` identifica la fórmula; cambia si la fórmula cambia.
"""

from src.enums import Severity

SCORING_VERSION = "2026.1"

# Peso de cada severidad para el riesgo acumulado.
_SEVERITY_WEIGHT = {
    Severity.HIGH: 1.0,
    Severity.MEDIUM: 0.5,
    Severity.LOW: 0.25,
}


def risk_score(signals) -> float:
    """Sospecha acumulada, monótona en severidades, saturada a `[0, 1]`.

    Recibe la lista de señales (objetos con `.severity`). Un caso sin señales
    tiene riesgo 0.
    """
    if not signals:
        return 0.0
    acumulado = sum(_SEVERITY_WEIGHT.get(s.severity, 0.0) for s in signals)
    return min(1.0, acumulado / 4.0)


def base_confidence(risk: float, *, degraded: bool = False) -> float:
    """Seguridad en el veredicto, con forma de U sobre el riesgo.

    - riesgo en un extremo (0 o 1) -> alta confianza (evidencia clara).
    - riesgo en el medio (≈0.5) -> baja confianza (evidencia contradictoria).
    - agentes degradados reducen la confianza sin mover el riesgo: una falla de
      agente no es evidencia de fraude (contrato §2.5).
    """
    confianza = 2.0 * abs(risk - 0.5)
    if degraded:
        confianza *= 0.5
    return max(0.0, min(1.0, confianza))
