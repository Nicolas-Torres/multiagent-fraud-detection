from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.config.settings import settings
from src.db.base import Base


class PolicyChunk(Base):
    """Corpus del RAG de políticas en el almacén vectorial (D8).

    Única tabla del esquema con columna vectorial. Almacena los chunks del
    catálogo `data/policies/fraud_policies_2025.1.json` con su embedding, para
    que el Internal Policy RAG los recupere por similitud semántica y los cite
    como respaldo del veredicto.

    **Sin índice vectorial a propósito**: `EMBEDDING_DIM=3072` es la dimensión
    nativa de `gemini-embedding-2`, y pgvector no permite HNSW/IVFFlat por
    encima de 2000 dimensiones. Con 11 políticas el scan coseno secuencial es
    instantáneo y exacto.
    """

    __tablename__ = "policy_chunks"

    chunk_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    policy_id: Mapped[str] = mapped_column(String(16), index=True)
    version: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(settings.embedding_dim))
    chunk_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict)
