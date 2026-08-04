"""Constantes compartidas por la capa de dominio.

La precedencia de `DecisionType` y los factores de moneda se comparten a
proposito entre el motor de agentes y el ground truth: si divergieran, el
harness mediria la discrepancia de reglas, no la calidad del sistema.
La logica de deteccion, en cambio, NO se comparte (D1 del diseno): el harness
debe medir la calidad, no validar el sistema contra si mismo.
"""

from decimal import Decimal

from src.enums import DecisionType

# --- Precedencia de DecisionType (contrato §2.2) ---
# Una transaccion puede satisfacer dos politicas con acciones distintas; gana
# la mas restrictiva. Es una regla del contrato, no del Arbiter: el ground
# truth la usa para construir la decision esperada.
PRECEDENCE = [
    DecisionType.BLOCK,
    DecisionType.ESCALATE_TO_HUMAN,
    DecisionType.CHALLENGE,
    DecisionType.APPROVE,
]


def precedence(acciones: set[DecisionType]) -> DecisionType:
    """La acción más restrictiva del conjunto, o `APPROVE` si no hay ninguna."""
    for accion in PRECEDENCE:
        if accion in acciones:
            return accion
    return DecisionType.APPROVE


# --- Acción prescrita por cada política del catálogo -------------------------
# Lo que el catálogo manda hacer, independiente de qué resultó ser el fraude.
# Lo usa el ground truth (build_ground_truth.py) y el piso determinístico del
# Arbiter para construir la decisión esperada.
POLICY_ACTION = {
    "FP-01": DecisionType.CHALLENGE,
    "FP-02": DecisionType.ESCALATE_TO_HUMAN,
    "FP-03": DecisionType.BLOCK,
    "FP-04": DecisionType.BLOCK,
    "FP-05": DecisionType.ESCALATE_TO_HUMAN,
    "FP-06": DecisionType.CHALLENGE,
    "FP-07": DecisionType.ESCALATE_TO_HUMAN,
    "FP-08": DecisionType.ESCALATE_TO_HUMAN,
    "FP-09": DecisionType.BLOCK,
    "FP-11": DecisionType.BLOCK,
}


def decision_desde_politicas(politicas: set[str]) -> DecisionType:
    """Veredicto por precedencia sobre las políticas citadas.

    Es el piso determinístico del Arbiter: la decisión que sale de aplicar la
    precedencia del contrato a las políticas recuperadas. El Arbiter con LLM
    puede ajustarla (con justificación); el modo determinístico del harness la
    usa tal cual.
    """
    acciones = {POLICY_ACTION[p] for p in politicas if p in POLICY_ACTION}
    return precedence(acciones)


def decision_desde_codigos(codigos: set[str], code_to_policy) -> DecisionType:
    """Veredicto por precedencia sobre las políticas detectadas por señal.

    El piso de "solo reglas": las señales **son** la detección determinística
    (los agentes sensores), así que el veredicto sale de las políticas que
    dispararon, no de textos recuperados. El RAG queda como respaldo citado.
    """
    politicas = {code_to_policy[c] for c in codigos if c in code_to_policy}
    return decision_desde_politicas(politicas)


# --- Factores de moneda de referencia (repaso 04 §3.7, contrato §2.5) ---
# La moneda es atributo de la cuenta. Para comparar montos entre cuentas o
# contra umbrales monetarios se convierte a una moneda de referencia (USD).
CURRENCY_FACTOR = {
    "PEN": Decimal("3.7"),
    "USD": Decimal("1.0"),
    "COP": Decimal("4000.0"),
    "EUR": Decimal("0.9"),
    "MXN": Decimal("18.0"),
    "ARS": Decimal("1000.0"),
    "CLP": Decimal("900.0"),
}


def to_reference(amount: Decimal, currency: str) -> Decimal:
    """Convierte un monto en la moneda de la cuenta a la moneda de referencia."""
    return amount / CURRENCY_FACTOR.get(currency, Decimal("1.0"))


# --- Comercios en lista negra del dataset (FP-07) ---
BLACKLISTED_MERCHANTS = frozenset({"M-999"})
