"""Las dos métricas determinísticas: sospecha y confianza.

El contrato expone **dos números y no uno** porque ninguna función monótona puede
producir los dos comportamientos:

| | `risk_score` | `base_confidence` |
|---|---|---|
| Muchas señales graves | alta | **alta** — `BLOCK` claro |
| Ninguna señal | baja | **alta** — `APPROVE` claro |
| Señales contradictorias | media | **baja** |
| Evidencia incompleta | sin cambio | **baja** |

La sospecha es monótona en las severidades; la confianza tiene forma de U. Y de
ahí sale la propiedad que más importa: **una falla de agente baja la confianza sin
mover el riesgo.** Un agente caído no es evidencia de fraude.

`risk_score` no lo puede ajustar el Arbiter: si un LLM pudiera moverlo, dejaría de
servir para vigilar drift (entregable 6).
"""

from collections.abc import Iterable, Sequence

from multiagent_fraud_detection.enums import DecisionType, Severity

#: Versión de **estas fórmulas**. Se sella en `Decision.scoring_version`: dos
#: scores producidos por versiones distintas no son comparables, y el harness
#: necesita saberlo para no promediar peras con manzanas.
SCORING_VERSION = "1.0"

SEVERITY_WEIGHT: dict[Severity, float] = {
    Severity.LOW: 0.10,
    Severity.MEDIUM: 0.25,
    Severity.HIGH: 0.50,
}

#: Cuánto baja la confianza por cada agente caído.
PENALTY_DEGRADED = 0.15
#: Cuánto baja cuando dos políticas prescriben acciones distintas.
PENALTY_CONTRADICTION = 0.10
#: Cuánto baja cuando faltó el perfil del cliente.
PENALTY_NO_PROFILE = 0.10
#: Piso: ninguna confianza llega a cero. Cero significaría "sin información", y
#: siempre hay alguna —aunque sea la de saber que la evidencia está incompleta—.
MIN_CONFIDENCE = 0.05


def risk_score(severities: Iterable[Severity]) -> float:
    """Sospecha acumulada, en [0, 1].

    Complemento probabilístico —*noisy-OR*—: cada señal reduce la probabilidad de
    que todo esté bien, y el riesgo es lo que queda. Tres propiedades que la
    hacen la forma correcta acá:

    - **Conmutativa.** Las señales llegan de dos agentes en paralelo y su orden de
      arribo es arbitrario; una fórmula sensible al orden daría scores distintos
      para la misma transacción.
    - **Monótona y acotada.** Agregar evidencia nunca baja el riesgo, y nunca
      pasa de 1 sin necesidad de recortes artificiales.
    - **Saturante.** La quinta señal *medium* pesa menos que la primera, que es
      como funciona la evidencia acumulada.

    Medida sobre las 7 000 del dataset separa mejor que la suma normalizada y que
    `max + conteo`: AUC 0.994, sin saturar los extremos.
    """
    resto = 1.0
    for severidad in severities:
        resto *= 1.0 - SEVERITY_WEIGHT[severidad]
    return round(1.0 - resto, 4)


def has_contradiction(
    actions: Iterable[DecisionType | None],
) -> bool:
    """¿Hay políticas que mandan cosas distintas?

    No es un error del catálogo: FP-01 pide `CHALLENGE` y FP-09 pide `BLOCK`, y
    las dos pueden aplicar a la misma transacción. La precedencia resuelve **qué
    hacer**; esto registra que hubo desacuerdo, que es información sobre cuánto
    confiar en el resultado.
    """
    distintas = {a for a in actions if a is not None}
    return len(distintas) > 1


def base_confidence(
    risk: float,
    *,
    degraded_agents: Sequence[str] = (),
    contradiction: bool = False,
    missing_profile: bool = False,
) -> float:
    """Seguridad en el veredicto, en [0.05, 1].

    Arranca de la forma de U —máxima en los extremos, mínima en el medio— y le
    resta lo que enturbia la lectura.

    La U vale `0.5 + |risk - 0.5|`, no `2·|risk - 0.5|`: el punto más ambiguo
    posible sigue mereciendo media confianza, porque el sistema *sí* sabe algo
    —sabe que es ambiguo—. Un cero ahí diría "no tengo información", y no es
    cierto.
    """
    valor = 0.5 + abs(risk - 0.5)
    valor -= PENALTY_DEGRADED * len(degraded_agents)
    if contradiction:
        valor -= PENALTY_CONTRADICTION
    if missing_profile:
        valor -= PENALTY_NO_PROFILE
    return round(max(MIN_CONFIDENCE, min(1.0, valor)), 4)


def signal_sort_key(code: str, severity: Severity) -> tuple[int, str]:
    """Orden determinístico: severidad descendente, luego código.

    Dos corridas idénticas tienen que persistir las señales en el mismo orden o
    el diff del harness es ruido, y el analista lee la cola de arriba hacia abajo
    —lo más grave primero—. El orden de producción no sirve: las señales llegan
    de dos agentes paralelos y su arribo es arbitrario.
    """
    peso = {Severity.HIGH: 0, Severity.MEDIUM: 1, Severity.LOW: 2}
    return (peso[severity], code)
