from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum as SQLEnum,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from multiagent_fraud_detection.db.base import Base
from multiagent_fraud_detection.enums import IndicatorType


class ThreatIndicator(Base):
    """Indicadores de compromiso recogidos de la web gobernada (ADR-0014).

    Segunda tabla de gobernanza, hermana de `merchant_blacklist`. La diferencia
    de forma es real y sale del uso: un comercio **está o no está** en lista
    negra, así que aquélla tiene PK natural y bandera; un emisor puede acumular
    varias alertas con fechas distintas, y la ventana de FP-10 necesita
    distinguirlas.

    **Nombre en plural**, contra sus dos hermanas de gobernanza: `merchant_blacklist`
    y `web_search_allowlist` describen *la lista*; esto describe *sus filas*, y
    cada fila es una observación con identidad propia.

    ## Las dos fechas

    `observed_at` es cuándo se publicó la alerta; `retrieved_at`, cuándo la
    trajimos. FP-10 —*"en últimas 24h"*— evalúa la primera, resuelta *as-of*
    contra el `timestamp` de la transacción (ADR-0004). Usar la segunda haría que
    un `fetch` de hoy volviera reciente una alerta de hace un año, que es
    precisamente el error que la ventana existe para evitar.

    ## Lo que la tabla NO tiene

    **Sin `severity`.** La severidad la declara el predicado, no el dato: es
    propiedad de la regla que consume el indicador, no del indicador. Mismo
    principio por el que `merchant_blacklist` no tiene columna de umbral —la
    tabla responde *quién*, la política responde *cuándo*—.
    """

    __tablename__ = "threat_indicators"

    # PK surrogate entera: la identidad es interna —no viaja al cliente— y
    # preserva orden de inserción gratis, igual que `signals.id`.
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    indicator_type: Mapped[IndicatorType] = mapped_column(
        SQLEnum(IndicatorType, native_enum=False, length=16)
    )

    #: El identificador observado: código de emisor, `device_id`, `merchant_id`.
    value: Mapped[str] = mapped_column(String(64))

    #: Cuándo se publicó la alerta. Lo que evalúa la ventana de 24h.
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    #: Cuándo la trajimos. Se proyecta a `ExternalCitation.retrieved_at`.
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    #: Pasó el allowlist en el camino de escritura (ADR-0014): si está acá, es
    #: porque la fuente estaba autorizada cuando se escribió.
    source_url: Mapped[str] = mapped_column(Text)

    #: Prosa plana, sin markdown. Se proyecta a `ExternalCitation.summary`.
    summary: Mapped[str] = mapped_column(Text)

    #: El sello. El lookup filtra por la generación vigente y eso es un
    #: invariante, no un filtro: mezclar generaciones haría mentir a
    #: `decisions.threat_intel_version`.
    snapshot_version: Mapped[str] = mapped_column(String(64))

    #: Baja lógica, igual que en la lista negra: retirar un indicador es una
    #: decisión de gobernanza y una fila borrada no se audita. El caso ya congeló
    #: su evidencia en `signals` y `citations_external`.
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))

    added_by: Mapped[str] = mapped_column(String)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        # Hace **idempotente** el fetch: re-ejecutarlo sobre el mismo corpus
        # actualiza en vez de duplicar. Sin esto, tres corridas dejarían tres
        # copias de la misma alerta y la ventana las contaría como tres.
        UniqueConstraint(
            "indicator_type",
            "value",
            "observed_at",
            "snapshot_version",
            name="uq_threat_indicators_observation",
        ),
        # Sin índice de lectura: son decenas de filas y se cachean en memoria
        # con TTL. El único camino que busca de verdad es el upsert del fetch, y
        # ese ya usa el índice del unique. Mismo criterio que `merchant_blacklist`.
    )
