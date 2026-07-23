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
