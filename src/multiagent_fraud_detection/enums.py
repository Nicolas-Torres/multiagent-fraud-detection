from enum import StrEnum

class Channel(StrEnum):
    WEB = "web"
    MOBILE = "mobile"


class CaseStatus(StrEnum):
    RECEIVED = "RECEIVED"
    ANALYZING = "ANALYZING"
    DECIDED = "DECIDED"
    PENDING_HUMAN = "PENDING_HUMAN"
    RESOLVED = "RESOLVED"
    FAILED = "FAILED"


class DecisionType(StrEnum):
    APPROVE = "APPROVE"
    CHALLENGE = "CHALLENGE"
    BLOCK = "BLOCK"
    ESCALATE_TO_HUMAN = "ESCALATE_TO_HUMAN"


class HumanAction(StrEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Segment(StrEnum):
    """Segmento comercial del cliente.

    Es enum y no `varchar` libre porque la aplicación **agrupa por él**: FP-08
    compara el monto contra el promedio del segmento. Un texto libre admitiría
    `Retail` y `retail` como grupos distintos y partiría el promedio en dos sin
    que nada falle.
    """
    RETAIL = "retail"
    PREMIUM = "premium"
    BUSINESS = "business"

class IndicatorType(StrEnum):
    """Qué clase de entidad señala un indicador de compromiso.

    Es enum y no `varchar` libre por el mismo motivo que `Segment`: la aplicación
    **agrupa por él** —el lookup es por `(tipo, valor)`— y un texto libre
    admitiría `issuer` e `Issuer` como claves distintas sin que nada falle.
    """
    ISSUER = "issuer"
    DEVICE = "device"
    MERCHANT = "merchant"
