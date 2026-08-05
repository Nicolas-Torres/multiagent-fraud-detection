from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    DateTime,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from multiagent_fraud_detection.db.base import Base

# Fijada por ADR-0012 y no configurable: cambiarla obliga a re-embeber el corpus
# entero, así que no es un parámetro sino una decisión sellada. 1536 y no las
# 3072 por defecto porque pgvector no indexa por encima de 2000 con HNSW ni
# IVFFlat, y el techo del índice se paga estructuralmente.
EMBEDDING_DIMENSIONS = 1536


class PolicyChunk(Base):
    """El índice vectorial: dato derivado, versionado y sellado. ADR-0012.

    Alimenta la **pierna de descubrimiento** del RAG (ADR-0011) —las políticas
    relacionadas que *no* dispararon—. La pierna de autorización no pasa por acá:
    ésa resuelve por identidad, con un lookup por `policy_id`, y por eso el
    veredicto sobrevive a que el proveedor de embeddings se caiga.

    **PK compuesta `(index_version, chunk_id)`.** Es lo que hace idempotente la
    re-indexación: reindexar dos veces con los mismos parámetros escribe sobre
    las mismas filas en vez de duplicarlas, y una segunda corrida que duplicara
    chunks envenenaría el ranking sin que nada fallara.

    **No hay poda de generaciones viejas** (ADR-0012 §6), así que un índice nuevo
    convive con el vigente. La contrapartida es que
    `WHERE index_version = <vigente>` deja de ser un filtro y pasa a ser un
    **invariante de corrección**: sin él la búsqueda mezcla generaciones y
    devuelve vecinos calculados con un modelo viejo —no falla, no lanza, no deja
    huella: devuelve resultados plausibles y peores—. Por eso vive en una única
    función de búsqueda del repositorio y no en cada llamador.

    **Sin índice aparte sobre `index_version`.** La PK ya crea un B-tree cuya
    columna líder es `index_version`; declarar otro sería una segunda copia del
    mismo árbol.

    **Sin índice ANN.** Once vectores se recorren exactos más rápido de lo que un
    HNSW los aproxima. Agregarlo después, con 1536 dimensiones, es una migración
    de una línea que **no** obliga a re-embeber.

    **`chunk_id` conserva su redundancia** con `policy_id`, `source_version` y
    `ordinal`, que la tabla ya guarda por separado. El identificador viaja al
    auditor dentro de `InternalCitation`, y uno legible se depura de un vistazo.
    El precio es el invariante `chunk_id == f"{policy_id}:{source_version}:{ordinal}"`,
    que afirma el chunker —escritor único— y cubre un test. No hay columna
    generada ni `CHECK`: punto ciego de `--autogenerate`.

    Que `chunk_id` lleve la versión del **documento** y no la del índice es lo
    que hace que una cita de enero siga resolviendo contra el índice
    reconstruido en marzo.
    """

    __tablename__ = "policy_chunks"

    # `gemini-embedding-2:1536:doc:1` — cadena descriptiva, no id opaco: el
    # motivo de sellarla es que alguien la lea sin una tabla de consulta al lado.
    index_version: Mapped[str] = mapped_column(String(64), primary_key=True)

    chunk_id: Mapped[str] = mapped_column(String(64), primary_key=True)

    policy_id: Mapped[str] = mapped_column(String(16))

    source_version: Mapped[str] = mapped_column(String(32))

    # Posición del fragmento dentro del documento. Hoy siempre 0 —un chunk por
    # documento—, pero el chunker está parametrizado: partir por párrafo es
    # configuración, no una migración.
    ordinal: Mapped[int] = mapped_column(Integer)

    content: Mapped[str] = mapped_column(Text)

    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS))

    embedded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        # Mismo argumento que en `policy_bindings`: un chunk de un documento que
        # no existe es un huérfano silencioso, y la base puede impedirlo sin que
        # nadie tenga que acordarse.
        ForeignKeyConstraint(
            ["policy_id", "source_version"],
            ["fraud_policies.policy_id", "fraud_policies.version"],
        ),
    )
