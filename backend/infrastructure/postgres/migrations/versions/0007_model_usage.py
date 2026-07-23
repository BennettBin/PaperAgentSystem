"""Persist conversation model token usage."""

from alembic import op

from backend.infrastructure.postgres.models import ModelUsageModel

revision = "0007_model_usage"
down_revision = "0006_model_runtime_config"
branch_labels = None
depends_on = None


def upgrade() -> None:
    ModelUsageModel.__table__.create(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    ModelUsageModel.__table__.drop(op.get_bind(), checkfirst=True)
