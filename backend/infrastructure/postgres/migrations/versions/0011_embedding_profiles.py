"""Persist embedding vector-space metadata and mark legacy vectors stale."""

import sqlalchemy as sa
from alembic import op

revision = "0011_embedding_profiles"
down_revision = "0010_blackboard_task_key"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    chunk_columns = {
        column["name"] for column in sa.inspect(bind).get_columns("document_chunks")
    }
    additions = (
        sa.Column("embedding_provider", sa.String(32), nullable=False, server_default="legacy"),
        sa.Column("embedding_version", sa.String(200), nullable=False, server_default="unknown"),
        sa.Column("embedding_dimension", sa.Integer(), nullable=False, server_default="1024"),
        sa.Column("embedding_max_length", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("embedding_normalized", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("embedding_fingerprint", sa.String(512), nullable=False, server_default=""),
        sa.Column("embedding_status", sa.String(32), nullable=False, server_default="stale"),
    )
    for column in additions:
        if column.name not in chunk_columns:
            op.add_column("document_chunks", column)
    if "embedding_model" in chunk_columns:
        op.execute(
            "UPDATE document_chunks SET embedding_provider = 'hash', "
            "embedding_model = 'multilingual-hash', embedding_version = 'v1', "
            "embedding_dimension = 1024, embedding_max_length = 0, "
            "embedding_normalized = true, "
            "embedding_fingerprint = "
            "'hash:multilingual-hash@v1:d1024:l0:n1', embedding_status = 'stale' "
            "WHERE embedding_model = 'multilingual-hash-v1'"
        )
    existing_indexes = {
        index["name"] for index in sa.inspect(bind).get_indexes("document_chunks")
    }
    if "ix_document_chunks_embedding_compatibility" not in existing_indexes:
        op.create_index(
            "ix_document_chunks_embedding_compatibility",
            "document_chunks",
            ["embedding_fingerprint", "embedding_status"],
        )

    for table_name in (
        "memory_segments",
        "conversation_summaries",
        "workspace_search",
    ):
        columns = {
            column["name"] for column in sa.inspect(bind).get_columns(table_name)
        }
        if "embedding_fingerprint" not in columns:
            op.add_column(
                table_name,
                sa.Column(
                    "embedding_fingerprint",
                    sa.String(512),
                    nullable=False,
                    server_default="",
                ),
            )


def downgrade() -> None:
    bind = op.get_bind()
    existing_indexes = {
        index["name"] for index in sa.inspect(bind).get_indexes("document_chunks")
    }
    if "ix_document_chunks_embedding_compatibility" in existing_indexes:
        op.drop_index(
            "ix_document_chunks_embedding_compatibility",
            table_name="document_chunks",
        )
    for table_name in (
        "workspace_search",
        "conversation_summaries",
        "memory_segments",
    ):
        columns = {
            column["name"] for column in sa.inspect(bind).get_columns(table_name)
        }
        if "embedding_fingerprint" in columns:
            op.drop_column(table_name, "embedding_fingerprint")
    columns = {
        column["name"] for column in sa.inspect(bind).get_columns("document_chunks")
    }
    for name in (
        "embedding_status",
        "embedding_fingerprint",
        "embedding_normalized",
        "embedding_max_length",
        "embedding_dimension",
        "embedding_version",
        "embedding_provider",
    ):
        if name in columns:
            op.drop_column("document_chunks", name)
