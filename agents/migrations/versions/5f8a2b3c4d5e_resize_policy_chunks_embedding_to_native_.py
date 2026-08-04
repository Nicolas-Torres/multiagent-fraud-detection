"""resize policy_chunks embedding to native 3072 and drop hnsw index

Revision ID: 5f8a2b3c4d5e
Revises: ee4df0d141e9
Create Date: 2026-08-03 21:00:00.000000

`gemini-embedding-2` produce 3072 dimensiones nativas; la columna quedó en 768
(truncada). pgvector 0.7 no permite HNSW/IVFFlat por encima de 2000
dimensiones, así que a 3072 se elimina el índice vectorial: con 11 políticas la
recuperación es un scan coseno secuencial exacto (D8).
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '5f8a2b3c4d5e'
down_revision: Union[str, Sequence[str], None] = 'ee4df0d141e9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("DROP INDEX IF EXISTS ix_policy_chunks_embedding")
    # La columna tiene datos a 768 dims; hay que vaciarla antes de cambiar el
    # tipo. El corpus se regenera con `scripts/index_policies.py`.
    op.execute("DELETE FROM policy_chunks")
    op.execute("ALTER TABLE policy_chunks ALTER COLUMN embedding TYPE vector(3072)")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DELETE FROM policy_chunks")
    op.execute("ALTER TABLE policy_chunks ALTER COLUMN embedding TYPE vector(768)")
    op.execute(
        "CREATE INDEX ix_policy_chunks_embedding ON policy_chunks "
        "USING hnsw (embedding vector_cosine_ops)"
    )
