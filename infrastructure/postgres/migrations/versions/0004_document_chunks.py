"""Parsed documents, traceable chunks, pgvector HNSW and FTS."""

from alembic import op
from sqlalchemy import Table

from infrastructure.postgres.models import DocumentChunkModel, ParsedDocumentModel

revision = "0004_document_chunks"
down_revision = "0003_subagent_runs"
branch_labels = None
depends_on = None

TABLES: tuple[Table, ...] = (  # type: ignore[assignment]
    ParsedDocumentModel.__table__,
    DocumentChunkModel.__table__,
)


def upgrade() -> None:
    bind = op.get_bind()
    for table in TABLES:
        table.create(bind=bind, checkfirst=True)
    if bind.dialect.name == "postgresql":
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_document_chunks_embedding_hnsw "
            "ON document_chunks USING hnsw (embedding vector_cosine_ops)"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_document_chunks_fts "
            "ON document_chunks USING gin (to_tsvector('simple', searchable_text))"
        )


def downgrade() -> None:
    bind = op.get_bind()
    for table in reversed(TABLES):
        table.drop(bind=bind, checkfirst=True)
