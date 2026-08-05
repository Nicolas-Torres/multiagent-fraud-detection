from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SQLEnum,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from multiagent_fraud_detection.db.base import Base
from multiagent_fraud_detection.enums import DecisionType


class PolicyBinding(Base):
    """La forma ejecutable de una política: nuestra traducción. ADR-0007.

    El otro artefacto del par. Acá vive todo lo que el motor interpreta —qué
    acción prescribe la norma y bajo qué condición— y nada de lo que el banco
    escribió.

    **PK compuesta `(binding_set_version, policy_id)`.** Una misma política puede
    estar traducida distinto en dos sets, y los dos tienen que poder coexistir:
    así se compara una traducción nueva contra la vigente antes de promoverla.

    **FK compuesta a `fraud_policies(policy_id, version)`.** Convierte en
    estructura la validación 5 del catálogo, que hoy es código: una vinculación
    no puede apuntar a un documento inexistente porque la base no la deja entrar.
    Es la misma clase de movimiento que hizo el `UNIQUE` en `cases.transaction_id`
    —la garantía la da la base, no el recordatorio—.

    **`condition` es JSONB nullable.** Nullable porque `null` es un valor con
    significado: la política se declara **no evaluable** y `excluded_reason`
    explica por qué (FP-10, ADR-0005). JSONB y no relacional por la regla de
    §7.2: forma anidada que se produce, se archiva y se lee entera junto a su
    dueño. El schema de esa columna es `PredicateSpec`, no el DDL.

    **`source_fingerprint` sin largo declarado.** El algoritmo es configurable
    por set (`binding_sets.fingerprint_algorithm`), así que un `String(71)`
    dimensionado para `sha256:` hornearía esa elección en el esquema y rompería
    el día que alguien elija `sha512`.

    Lo que **no** está: `requires`, `owner`, `signals` y `evaluable`. Los cuatro
    se derivan de `condition` al cargar. Guardarlos sería poder desincronizarlos.
    """

    __tablename__ = "policy_bindings"

    binding_set_version: Mapped[str] = mapped_column(
        ForeignKey("binding_sets.version", ondelete="CASCADE"),
        primary_key=True,
    )

    policy_id: Mapped[str] = mapped_column(String(16), primary_key=True)

    source_version: Mapped[str] = mapped_column(String(32))

    source_fingerprint: Mapped[str] = mapped_column(String)

    action: Mapped[DecisionType] = mapped_column(
        SQLEnum(DecisionType, native_enum=False)
    )

    condition: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)

    excluded_reason: Mapped[str | None] = mapped_column(Text)

    # Baja lógica, igual que en `merchant_blacklist`: retirar una traducción es
    # una decisión que hay que poder auditar, y una fila borrada no se audita.
    # El loader la lee y produce `EXCLUDED`.
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))

    # Quién tradujo la norma y cuándo. No son `added_by` / `added_at`: cargan el
    # sentido de ADR-0007 —hubo un acto de traducción con un responsable— y por
    # eso no se uniforman con los campos de alta de las tablas de gobernanza.
    bound_by: Mapped[str] = mapped_column(String)

    bound_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["policy_id", "source_version"],
            ["fraud_policies.policy_id", "fraud_policies.version"],
        ),
    )
