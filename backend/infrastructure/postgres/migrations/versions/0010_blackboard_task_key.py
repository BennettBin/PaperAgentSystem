"""Scope Blackboard entry identity by Task as required by the runtime contract."""

from alembic import op
from sqlalchemy import inspect

revision = "0010_blackboard_task_key"
down_revision = "0009_blackboard"
branch_labels = None
depends_on = None


def upgrade() -> None:
    sqlite = op.get_bind().dialect.name == "sqlite"
    existing_name = inspect(op.get_bind()).get_pk_constraint("blackboard_entries").get("name")
    with op.batch_alter_table(
        "blackboard_entries",
        naming_convention={"pk": "pk_%(table_name)s"} if sqlite else None,
    ) as batch_op:
        batch_op.drop_constraint(
            str(existing_name or "pk_blackboard_entries"),
            type_="primary",
        )
        batch_op.create_primary_key(
            "blackboard_entries_pkey",
            ["entry_id", "workspace_id", "task_id"],
        )


def downgrade() -> None:
    sqlite = op.get_bind().dialect.name == "sqlite"
    existing_name = inspect(op.get_bind()).get_pk_constraint("blackboard_entries").get("name")
    with op.batch_alter_table(
        "blackboard_entries",
        naming_convention={"pk": "pk_%(table_name)s"} if sqlite else None,
    ) as batch_op:
        batch_op.drop_constraint(
            str(existing_name or "pk_blackboard_entries"),
            type_="primary",
        )
        batch_op.create_primary_key(
            "blackboard_entries_pkey",
            ["entry_id", "workspace_id"],
        )
