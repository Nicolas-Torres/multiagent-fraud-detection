"""Perfil de comportamiento del cliente.

Devuelve `CustomerBehaviorRead`, no el modelo ORM, y no es un detalle: el mismo
objeto viaja a `cases.customer_snapshot` como **snapshot congelado** del análisis.
Un objeto adjunto a la sesión seguiría reflejando cambios posteriores; uno
detachado no.

> Congela lo mutable, referencia lo inmutable.

De paso, es el mismo tipo que reciben los predicados en los tests y en
`check_policies.py`: el dominio ve la misma forma venga de Postgres o de un CSV.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from multiagent_fraud_detection.db.models import CustomerBehavior
from multiagent_fraud_detection.schemas.customer_behavior import CustomerBehaviorRead


async def profile_for(
    session: AsyncSession, *, customer_id: str
) -> CustomerBehaviorRead | None:
    """El perfil vigente, o `None` si el cliente no tiene uno.

    `None` **no es un error**: un cliente sin historial de comportamiento es un
    escenario válido —y, según el contrato, el que más importa—. Quien llama lo
    traduce en señal, no en excepción.
    """
    fila = await session.get(CustomerBehavior, customer_id)
    return CustomerBehaviorRead.model_validate(fila) if fila is not None else None
