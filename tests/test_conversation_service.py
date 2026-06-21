from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from conversations.service import ConversationService
from core.domain.file import File
from core.domain.user import User, Workspace
from infrastructure.postgres.models import Base
from infrastructure.postgres.repositories import (
    SqlAlchemyConversationRepository,
    SqlAlchemyFileRepository,
    SqlAlchemyMessageRepository,
    SqlAlchemyUserRepository,
    SqlAlchemyWorkspaceRepository,
)


@pytest.fixture
def context():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine, expire_on_commit=False)
    users = SqlAlchemyUserRepository(session)
    workspaces = SqlAlchemyWorkspaceRepository(session)
    conversations = SqlAlchemyConversationRepository(session)
    messages = SqlAlchemyMessageRepository(session)
    files = SqlAlchemyFileRepository(session)
    yield session, users, workspaces, files, ConversationService(conversations, messages), messages
    session.close()


@pytest.mark.asyncio
async def test_crud_search_pagination_sort_and_workspace_isolation(context):
    session, users, workspaces, _, service, _ = context
    user = User.create("history@example.com", "History")
    await users.save(user)
    first_ws, second_ws = Workspace.create(user.id, "one"), Workspace.create(user.id, "two")
    await workspaces.save(first_ws)
    await workspaces.save(second_ws)
    old = await service.create(first_ws.id, user.id, "Old paper")
    new = await service.create(first_ws.id, user.id, "New paper")
    await service.create(second_ws.id, user.id, "Other workspace")
    old.updated_at = datetime.now(UTC) - timedelta(days=1)
    await service.conversations.save(old)
    session.commit()

    results = await service.search(first_ws.id, "paper", 0, 10)
    assert [item.id for item in results] == [new.id, old.id]
    assert len(await service.search(first_ws.id, "", 0, 1)) == 1
    renamed = await service.rename(old.id, first_ws.id, "Renamed")
    session.commit()
    assert renamed.title == "Renamed"
    assert all(item.workspace_id == first_ws.id for item in await service.search(first_ws.id))


@pytest.mark.asyncio
async def test_messages_attachments_range_delete_and_conversation_cascade(context):
    session, users, workspaces, files, service, messages = context
    user = User.create("messages@example.com", "Messages")
    await users.save(user)
    workspace = Workspace.create(user.id, "workspace")
    await workspaces.save(workspace)
    conversation = await service.create(workspace.id, user.id, "Thread")
    file = File.create(
        workspace.id, "paper.pdf", "application/pdf", 4, "uploads/paper", "b" * 64
    )
    await files.save(file)
    first = await service.add_message(
        conversation.id, workspace.id, "first", file_ids=[file.id]
    )
    second = await service.add_message(conversation.id, workspace.id, "second")
    second.created_at = first.created_at + timedelta(seconds=5)
    await messages.save(second)
    session.commit()

    assert await messages.list_file_ids(first.id, workspace.id) == [file.id]
    listed = await messages.list_by_conversation(conversation.id, workspace.id)
    assert [item.id for item in listed] == [first.id, second.id]
    deleted = await service.delete_message_range(
        conversation.id,
        workspace.id,
        first.created_at - timedelta(seconds=1),
        first.created_at + timedelta(seconds=1),
    )
    session.commit()
    assert deleted == 1
    assert [item.id for item in await messages.list_by_conversation(conversation.id, workspace.id)] == [second.id]
    assert await service.delete_conversation(conversation.id, workspace.id)
    session.commit()
    assert await messages.list_by_conversation(conversation.id, workspace.id) == []
