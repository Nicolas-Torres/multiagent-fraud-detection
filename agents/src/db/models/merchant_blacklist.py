from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base


class MerchantBlacklist(Base):
    """Comercios marcados como fraudulentos. Insumo de FP-07.

    Primera tabla de **gobernanza** del proyecto: dato mutable, administrado por
    un humano, con audit trail. Es la categoría que el §4 del contrato definió
    para `web_search_allowlist`, y comparte su forma a propósito.

    > ¿Es config de infraestructura (estática, por deploy) o dato de gobernanza
    > (mutable, con audit trail)? Lo primero → env var. Lo segundo → tabla.

    **Nombre en singular**, contra la convención plural de las otras siete
    tablas. El nombre describe la lista, no sus filas, igual que su hermana
    `web_search_allowlist`. Las dos se administran y se leen juntas; la
    consistencia entre ellas pesa más que la regla general.

    **Sin columna de umbral**: FP-07 exige que el monto supere un mínimo, pero
    ese umbral es texto de la política y vive en el catálogo. La tabla responde
    *quién*; la política responde *cuándo*.
    """

    __tablename__ = "merchant_blacklist"

    # PK natural con bandera `active`, no surrogate con historial de altas y
    # bajas. La consulta real es un lookup puntual —"¿este comercio está en
    # lista negra?"— y el historial no se pierde: el caso **congela su propia
    # evidencia** en `signals`. Si el comercio se retira en marzo, el caso de
    # enero sigue diciendo qué decidió y por qué. Mismo principio que
    # `cases.customer_snapshot`.
    merchant_id: Mapped[str] = mapped_column(String, primary_key=True)

    # Baja lógica, no `DELETE`: retirar un comercio de la lista es una decisión
    # de gobernanza que hay que poder auditar, y una fila borrada no se audita.
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))

    reason: Mapped[str] = mapped_column(Text)

    added_by: Mapped[str] = mapped_column(String)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Sin índice en `active`: son unidades de filas y se cachean en memoria con
    # invalidación al escribir (§4 del contrato). Un índice sería ceremonia.
