"""Add persistent document section catalog and chunk section metadata."""

import sqlalchemy as sa
from alembic import op

from infrastructure.postgres.models import DocumentSectionModel

revision = "0008_document_sections"
down_revision = "0007_model_usage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    DocumentSectionModel.__table__.create(bind, checkfirst=True)
    existing_columns = {
        column["name"] for column in sa.inspect(bind).get_columns("document_chunks")
    }
    columns = (
        sa.Column("section_id", sa.String(length=64), nullable=True),
        sa.Column("section_number", sa.String(length=32), nullable=True),
        sa.Column("section_title", sa.String(length=300), nullable=True),
        sa.Column("chunk_index_in_section", sa.Integer(), nullable=True),
    )
    for column in columns:
        if column.name not in existing_columns:
            op.add_column("document_chunks", column)

    existing_indexes = {
        index["name"] for index in sa.inspect(bind).get_indexes("document_chunks")
    }
    indexes = (
        ("ix_document_chunks_section_id", ["section_id"]),
        ("ix_document_chunks_section_number", ["section_number"]),
    )
    for name, column_names in indexes:
        if name not in existing_indexes:
            op.create_index(name, "document_chunks", column_names)


def downgrade() -> None:
    bind = op.get_bind()
    existing_indexes = {
        index["name"] for index in sa.inspect(bind).get_indexes("document_chunks")
    }
    for name in (
        "ix_document_chunks_section_number",
        "ix_document_chunks_section_id",
    ):
        if name in existing_indexes:
            op.drop_index(name, table_name="document_chunks")

    existing_columns = {
        column["name"] for column in sa.inspect(bind).get_columns("document_chunks")
    }
    for name in (
        "chunk_index_in_section",
        "section_title",
        "section_number",
        "section_id",
    ):
        if name in existing_columns:
            op.drop_column("document_chunks", name)
    DocumentSectionModel.__table__.drop(bind, checkfirst=True)
