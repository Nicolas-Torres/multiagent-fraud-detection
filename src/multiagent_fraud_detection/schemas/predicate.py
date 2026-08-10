from typing import Literal

from pydantic import BaseModel, ConfigDict

from multiagent_fraud_detection.enums import Severity


class ParamSpecRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    kind: Literal["number", "integer", "choice"]
    label: str
    minimum: float | None = None
    maximum: float | None = None
    choices: tuple[str, ...] = ()


class PredicateSpec(BaseModel):
    """Respuesta de `GET /api/v1/predicates`: la biblioteca para el
    compositor del dashboard (§2.3, §3.3 del contrato).

    Sin `fn` ni el valor crudo de `signal`: el primero no es serializable, y
    el segundo puede depender de los parámetros (`count_in_window` elige
    entre `DEVICE_VELOCITY`/`CUSTOMER_VELOCITY` según el eje) — mostrar sólo
    el caso estático confundiría más de lo que informa.
    """

    name: str
    requires: list[str]
    severity: Severity
    params: dict[str, ParamSpecRead]
    description: str
