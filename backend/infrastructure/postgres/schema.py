"""Database schema bootstrap helpers."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import Engine


def ensure_database_schema(engine: Engine) -> None:
    """Bring the configured database to the latest Alembic revision."""

    if engine.dialect.name == "postgresql":
        with engine.begin() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

    root = Path(__file__).resolve().parents[3]
    config = Config(str(root / "infrastructure" / "database" / "alembic.ini"))
    config.set_main_option(
        "sqlalchemy.url", engine.url.render_as_string(hide_password=False)
    )
    command.upgrade(config, "head")
