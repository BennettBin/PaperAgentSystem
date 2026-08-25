"""Add V2 evidence spans and semantic element metadata to document chunks."""

import sqlalchemy as sa
from alembic import op

revision = "0012_document_chunk_evidence"
down_revision = "0011_embedding_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {
        column["name"] for column in sa.inspect(bind).get_columns("document_chunks")
    }
    additions = (
        sa.Column("evidence_spans", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("element_types", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("content_kind", sa.String(32), nullable=False, server_default="body"),
        sa.Column(
            "contains_inferred_content",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    for column in additions:
        if column.name not in columns:
            op.add_column("document_chunks", column)
    indexes = {
        index["name"] for index in sa.inspect(bind).get_indexes("document_chunks")
    }
    if "ix_document_chunks_content_kind" not in indexes:
        op.create_index(
            "ix_document_chunks_content_kind",
            "document_chunks",
            ["content_kind"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    indexes = {
        index["name"] for index in sa.inspect(bind).get_indexes("document_chunks")
    }
    if "ix_document_chunks_content_kind" in indexes:
        op.drop_index("ix_document_chunks_content_kind", table_name="document_chunks")
    columns = {
        column["name"] for column in sa.inspect(bind).get_columns("document_chunks")
    }
    for name in (
        "contains_inferred_content",
        "content_kind",
        "element_types",
        "evidence_spans",
    ):
        if name in columns:
            op.drop_column("document_chunks", name)
