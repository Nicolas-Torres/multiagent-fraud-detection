from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from multiagent_fraud_detection.db.base import Base


class FraudPolicy(Base):
    """El documento normativo del banco. Fase 3 de ADR-0007.

    Uno de los dos artefactos con dueños distintos que el catálogo junta: acá
    vive lo que el banco publica, y en `policy_bindings` lo que nosotros
    traducimos. La separación es la decisión de ADR-0007 y esta tabla no la
    negocia: **no** guarda `action`, ni `condition`, ni nada ejecutable.

    **PK compuesta `(policy_id, version)`.** `InternalCitation` ya trata al par
    como la referencia citable, y la tabla es append-only por versión: publicar
    `FP-01` en `2025.2` no reemplaza a `FP-01` en `2025.1`, la acompaña. Las
    citas persistidas siguen resolviendo contra el texto que se citó.

    **Sin columna `active`.** El patrón de `merchant_blacklist` invita a
    copiarla, pero ahí la bandera *es* el dato: la pertenencia a la lista negra
    es lo que se administra. Acá los cuatro estados —`ACTIVE`, `EXCLUDED`,
    `PENDING`, `STALE`— son **derivados** al cargar, y una columna `active` sería
    una segunda fuente de verdad sobre *¿esta política aplica?* compitiendo con
    `PolicyState`. El retiro ya es expresable: `policy_bindings.active = false`
    → `EXCLUDED`, o simplemente no publicar vinculación para la versión nueva.

    **Sin columna de huella.** La huella no se guarda del lado del documento: se
    calcula al cargar y se compara contra la que registró la vinculación. Si
    viviera acá, editar el texto y la huella en el mismo `UPDATE` dejaría el
    estado `STALE` fuera de alcance —que es justo lo que ADR-0007 quiere poder
    detectar—.

    **La columna se llama `text` y el JSON del banco la llama `rule`.** Cuál de
    los dos nombres se hasheó lo dice `binding_sets.fingerprint_field`, no esta
    tabla: el nombre de acá es nuestro y es estable, el de allá es del formato de
    entrega y puede cambiar entre catálogos. `DbCatalogSource` traduce.
    """

    __tablename__ = "fraud_policies"

    policy_id: Mapped[str] = mapped_column(String(16), primary_key=True)

    version: Mapped[str] = mapped_column(String(32), primary_key=True)

    text: Mapped[str] = mapped_column(Text)

    created_by: Mapped[str] = mapped_column(String)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
