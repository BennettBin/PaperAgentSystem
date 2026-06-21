"""Persist parent-child sub Agent runs."""

from alembic import op
from sqlalchemy import Table

from infrastructure.postgres.models import SubAgentRunModel

revision = "0003_subagent_runs"
down_revision = "0002_workspace_memory"
branch_labels = None
depends_on = None

TABLES: tuple[Table, ...] = (SubAgentRunModel.__table__,)  # type: ignore[assignment]


def upgrade() -> None:
    bind = op.get_bind()
    for table in TABLES:
        table.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for table in reversed(TABLES):
        table.drop(bind=bind, checkfirst=True)
