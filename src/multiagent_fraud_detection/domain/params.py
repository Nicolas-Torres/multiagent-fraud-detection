"""Parámetros de evaluación del motor determinístico.

Esto **no** son políticas. Una política la escribe el banco y su traducción vive
en `data/policies/policy_bindings_*.json` (ADR-0007). Acá viven los parámetros
que la evaluación necesita y que ninguna norma menciona: la conversión entre
monedas, el agregado poblacional contra el que compara FP-08, y la regla de
precedencia cuando dos políticas aplican a la vez.

La distinción importa por una razón concreta: el etiquetador
(`scripts/build_ground_truth.py`) y el intérprete son **dos implementaciones
independientes a propósito**, y su desacuerdo es un hallazgo. Pero sólo si
desacuerdan sobre *lógica*. Un desacuerdo sobre el factor del sol no prueba
nada: es ruido con forma de hallazgo. Por eso las constantes se comparten y las
reglas no.
"""

from types import MappingProxyType

from multiagent_fraud_detection.enums import DecisionType

# Versión de los parámetros. Se sella en `Decision.scoring_version` junto con la
# fórmula de scoring: una decisión evaluada con otros promedios no es comparable.
PARAMS_VERSION = "1.0"

# Moneda en la que se expresan todos los umbrales monetarios de las
# vinculaciones (`threshold_ref`, `ceiling_ref`). Nunca literales por moneda.
REFERENCE_CURRENCY = "USD"

# Unidades de cada moneda por unidad de la moneda de referencia.
#
# Son tasas de juguete, fijas y redondas: el dataset es sintético y lo que se
# necesita es que un umbral signifique lo mismo en las siete monedas, no que
# refleje el mercado. Una tasa real haría irreproducible el ground truth —el
# mismo script daría etiquetas distintas según el día en que se corriera—.
CURRENCY_FACTOR = MappingProxyType({
    "PEN": 3.7,
    "USD": 1.0,
    "COP": 4000.0,
    "EUR": 0.9,
    "MXN": 18.0,
    "ARS": 1000.0,
    "CLP": 900.0,
})

# Promedio de `usual_amount_avg` por segmento, en moneda de referencia, sobre
# los 1 000 perfiles del dataset. Es el umbral contra el que compara FP-08.
#
# **Congelado, no calculado.** Consultarlo en runtime tiene dos problemas: se
# mueve con la población, así que el harness deja de ser reproducible sin que
# nada falle; y el perfil es mutable, así que el valor de hoy no es el que
# existía cuando ocurrió una transacción de enero —el mismo argumento por el que
# el historial se consulta *as-of* (ADR-0004)—.
#
# Precisión completa a propósito. Con dos decimales el ground truth también se
# reproduce, pero sólo porque ninguna transacción del dataset cae entre los dos
# umbrales. Eso es suerte, y la suerte no es una garantía.
SEGMENT_AVG_REF = MappingProxyType({
    "retail": 634.3463814118472,
    "premium": 1847.5933988956547,
    "business": 4778.644399643911,
})

# Cuando dos políticas aplican a la vez gana la más restrictiva. La misma regla
# tiene que usar el Arbiter, o la comparación contra el ground truth es injusta.
PRECEDENCE = ("BLOCK", "ESCALATE_TO_HUMAN", "CHALLENGE", "APPROVE")


def precedencia(decision: DecisionType) -> int:
    """Qué tan restrictiva es una decisión: mayor número, más restrictiva.

    Es la inversa del índice en `PRECEDENCE` —que resuelve conflictos por
    "la primera que aparece", con `BLOCK` primero— para que la restricción de
    ADR-0016 se lea tal cual la escribe el ADR: `precedencia(decision) >=
    precedencia(piso)` es "el Arbiter no bajó del piso".
    """
    return len(PRECEDENCE) - 1 - PRECEDENCE.index(decision.value)


def to_reference(amount: float, currency: str) -> float:
    """Convierte un monto a la moneda de referencia."""
    return amount / CURRENCY_FACTOR[currency]


def from_reference(amount_ref: float, currency: str) -> float:
    """Convierte un umbral expresado en moneda de referencia a `currency`.

    Es la dirección que usan los predicados: el umbral viaja hacia la moneda de
    la transacción, no al revés. Comparar en la moneda original evita una
    división por transacción y mantiene el monto sin tocar.
    """
    return amount_ref * CURRENCY_FACTOR[currency]
