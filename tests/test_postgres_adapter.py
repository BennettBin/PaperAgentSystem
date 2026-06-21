from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.orm.exc import StaleDataError

from core.domain.conversation import Conversation, Message
from core.domain.file import File
from core.domain.task import Task
from core.domain.user import User, Workspace
from infrastructure.postgres.models import Base, ConversationModel
from infrastructure.postgres.repositories import (
    SqlAlchemyConversationRepository,
    SqlAlchemyFileRepository,
    SqlAlchemyMessageRepository,
    SqlAlchemyTaskRepository,
    SqlAlchemyUserRepository,
    SqlAlchemyWorkspaceRepository,
)


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as value:
        yield value


@pytest.mark.asyncio
async def test_repository_contract_and_workspace_isolation(session):
    users = SqlAlchemyUserRepository(session)
    workspaces = SqlAlchemyWorkspaceRepository(session)
    conversations = SqlAlchemyConversationRepository(session)
    messages = SqlAlchemyMessageRepository(session)
    tasks = SqlAlchemyTaskRepository(session)

    user = User.create("reader@example.com", "Reader")
    await users.save(user)
    ws1, ws2 = Workspace.create(user.id, "one"), Workspace.create(user.id, "two")
    await workspaces.save(ws1)
    await workspaces.save(ws2)
    conv = Conversation.create(ws1.id, user.id, "Paper")
    await conversations.save(conv)
    message = Message.create_user_message(conv.id, "hello")
    await messages.save(message)
    task = Task.create(ws1.id, user.id, conv.id, "analyze")
    await tasks.save(task)
    session.commit()

    assert await users.find_by_email(user.email) is not None
    assert await workspaces.verify_workspace_access(ws1.id, user.id)
    assert await conversations.find_by_id(conv.id, ws1.id) is not None
    assert await conversations.find_by_id(conv.id, ws2.id) is None
    assert await messages.find_by_id(message.id, ws2.id) is None
    assert await tasks.find_by_id(task.id, ws1.id) is not None
    assert await tasks.find_by_id(task.id, ws2.id) is None


@pytest.mark.asyncio
async def test_soft_delete_and_file_reference_count(session):
    users = SqlAlchemyUserRepository(session)
    workspaces = SqlAlchemyWorkspaceRepository(session)
    files = SqlAlchemyFileRepository(session)
    user = User.create("files@example.com", "Files")
    await users.save(user)
    workspace = Workspace.create(user.id, "files")
    await workspaces.save(workspace)
    file = File.create(
        workspace.id, "paper.pdf", "application/pdf", 4, "uploads/x", "a" * 64
    )
    await files.save(file)
    session.commit()

    assert await files.delete(file.id, workspace.id)
    session.commit()
    assert await files.find_by_id(file.id, workspace.id) is None


def test_optimistic_lock_conflict():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as seed:
        seed.add(
            ConversationModel(
                id="c",
                workspace_id="w",
                user_id="u",
                title="one",
                description=None,
            )
        )
        seed.commit()
    left, right = factory(), factory()
    try:
        a, b = left.get(ConversationModel, "c"), right.get(ConversationModel, "c")
        assert a is not None and b is not None
        a.title = "left"
        left.commit()
        b.title = "right"
        with pytest.raises(StaleDataError):
            right.commit()
    finally:
        left.close()
        right.close()


def test_alembic_upgrade_and_downgrade_empty_database(tmp_path):
    database = tmp_path / "migration.db"
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database.as_posix()}")
    command.upgrade(config, "head")
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    assert "users" in inspect(engine).get_table_names()
    command.downgrade(config, "base")
    assert inspect(engine).get_table_names() == ["alembic_version"]
