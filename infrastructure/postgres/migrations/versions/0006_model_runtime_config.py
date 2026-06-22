"""Persist selected small and large model versions."""

from alembic import op

from infrastructure.postgres.models import ModelRuntimeConfigModel

revision = "0006_model_runtime_config"
down_revision = "0005_trace_spans"
branch_labels = None
depends_on = None


def upgrade() -> None:
    ModelRuntimeConfigModel.__table__.create(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    ModelRuntimeConfigModel.__table__.drop(bind=op.get_bind(), checkfirst=True)
