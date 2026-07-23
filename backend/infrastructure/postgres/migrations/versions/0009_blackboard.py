"""Add persistent append-only Evidence Blackboard tables."""

from alembic import op

from backend.infrastructure.postgres.models import BlackboardEntryModel, BlackboardEventModel

revision = "0009_blackboard"
down_revision = "0008_document_sections"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    BlackboardEntryModel.__table__.create(bind, checkfirst=True)
    BlackboardEventModel.__table__.create(bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    BlackboardEventModel.__table__.drop(bind, checkfirst=True)
    BlackboardEntryModel.__table__.drop(bind, checkfirst=True)
