"""Tipos de dominio compartidos por los schemas de la frontera.

Se extrae un tipo cuando tiene **dos consumidores reales**, no cuando se
anticipa el segundo. Nombrar por concepto de negocio (`CountryCode`), nunca por
forma (`Str2`).
"""

from decimal import Decimal
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AfterValidator, Field, StringConstraints

CountryCode = Annotated[
    str, StringConstraints(min_length=2, max_length=2, to_upper=True)
]

CurrencyCode = Annotated[
    str, StringConstraints(min_length=3, max_length=3, to_upper=True)
]

Money = Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=2)]

Confidence = Annotated[float, Field(ge=0.0, le=1.0)]


def _validar_zona_iana(valor: str) -> str:
    """Rechaza una zona horaria que la stdlib no reconozca.

    Validar, no mutar: una zona inválida no se puede corregir sin adivinar
    —`"America/Mexico City"` con espacio podría ser Ciudad de México o
    Monterrey—, así que se rechaza en la frontera.

    Es la única validación del perfil cuyo error no se nota hasta que corre un
    agente: una zona mal escrita no rompe la escritura, corre la ventana horaria
    del cliente varias horas y FP-01 evalúa otra cosa.
    """
    try:
        ZoneInfo(valor)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"zona horaria IANA inválida: {valor!r}") from exc
    return valor


TimeZone = Annotated[str, AfterValidator(_validar_zona_iana)]
