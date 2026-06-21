"""Persistent task trace spans."""

from alembic import op
from sqlalchemy import Table

from infrastructure.postgres.models import TraceSpanModel

revision = "0005_trace_spans"
down_revision = "0004_document_chunks"
branch_labels = None
depends_on = None

TABLES: tuple[Table, ...] = (TraceSpanModel.__table__,)  # type: ignore[assignment]


def upgrade() -> None:
    bind = op.get_bind()
    for table in TABLES:
        table.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for table in reversed(TABLES):
        table.drop(bind=bind, checkfirst=True)
