"""Workspace, search and memory tables."""

from alembic import op
from sqlalchemy import Table

from infrastructure.postgres.models import (
    ConversationSummaryModel,
    MemoryPreferenceModel,
    MemorySegmentModel,
    MessageFileModel,
    WorkspaceEntryModel,
    WorkspaceSearchModel,
)

revision = "0002_workspace_memory"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

TABLES: tuple[Table, ...] = (  # type: ignore[assignment]
    MessageFileModel.__table__,
    WorkspaceEntryModel.__table__,
    WorkspaceSearchModel.__table__,
    MemorySegmentModel.__table__,
    ConversationSummaryModel.__table__,
    MemoryPreferenceModel.__table__,
)


def upgrade() -> None:
    bind = op.get_bind()
    for table in TABLES:
        table.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for table in reversed(TABLES):
        table.drop(bind=bind, checkfirst=True)
