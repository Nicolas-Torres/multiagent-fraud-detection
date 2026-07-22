"""Tipos de dominio compartidos por los schemas de la frontera."""

from decimal import Decimal
from typing import Annotated

from pydantic import Field, StringConstraints

CountryCode = Annotated[
    str, StringConstraints(min_length=2, max_length=2, to_upper=True)
]

Money = Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=2)]
