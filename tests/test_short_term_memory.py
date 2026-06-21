import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.domain.conversation import Conversation, Message
from core.domain.user import User, Workspace
from infrastructure.fake.llm_clients import FakeEmbeddingClient
from infrastructure.postgres.models import Base
from infrastructure.postgres.repositories import (
    SqlAlchemyConversationRepository,
    SqlAlchemyMessageRepository,
    SqlAlchemyUserRepository,
    SqlAlchemyWorkspaceRepository,
)
from memory.short_term import ShortTermMemoryService


@pytest.fixture
def context():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    session = factory()
    return (
        session,
        factory,
        SqlAlchemyUserRepository(session),
        SqlAlchemyWorkspaceRepository(session),
        SqlAlchemyConversationRepository(session),
        SqlAlchemyMessageRepository(session),
        ShortTermMemoryService(factory, FakeEmbeddingClient(), message_threshold=8),
    )


@pytest.mark.asyncio
async def test_recent_window_summary_trace_and_invalidation(context):
    session, _, users, workspaces, conversations, messages, memory = context
    user = User.create("memory@example.com", "Memory")
    await users.save(user)
    workspace = Workspace.create(user.id, "memory")
    await workspaces.save(workspace)
    conversation = Conversation.create(workspace.id, user.id, "Long")
    await conversations.save(conversation)
    created = []
    for index in range(10):
        message = Message.create_user_message(
            conversation.id, f"historical fact token{index} value{index}"
        )
        await messages.save(message)
        created.append(message)
    session.commit()

    assert len(memory.recent_messages(workspace.id, conversation.id, 8)) == 8
    segment_id = await memory.summarize_if_needed(workspace.id, conversation.id)
    assert segment_id
    recalled = await memory.recall(workspace.id, conversation.id, "token7 value7", top_k=5)
    assert recalled[0].segment_id == segment_id
    assert len(recalled[0].source_messages) == 10
    assert any(item["message_id"] == str(created[7].id) for item in recalled[0].source_messages)

    await messages.delete(created[7].id, workspace.id)
    assert memory.invalidate_for_message(str(created[7].id), workspace.id) == 1
    session.commit()
    assert await memory.recall(workspace.id, conversation.id, "token7") == []
    rebuilt = await memory.summarize_if_needed(workspace.id, conversation.id)
    assert rebuilt and rebuilt != segment_id


@pytest.mark.asyncio
async def test_twenty_conversation_recall_and_fact_preservation(context):
    session, _, users, workspaces, conversations, messages, memory = context
    user = User.create("dataset@example.com", "Dataset")
    await users.save(user)
    workspace = Workspace.create(user.id, "dataset")
    await workspaces.save(workspace)
    recall_hits = 0
    fact_hits = 0
    total = 0
    for conv_index in range(20):
        conversation = Conversation.create(workspace.id, user.id, f"Conversation {conv_index}")
        await conversations.save(conversation)
        for question_index in range(10):
            content = (
                f"project{conv_index} question{question_index} "
                f"answer fact{conv_index}_{question_index}"
            )
            await messages.save(Message.create_user_message(conversation.id, content))
        session.commit()
        await memory.summarize_if_needed(workspace.id, conversation.id)
        for question_index in range(10):
            total += 1
            token = f"fact{conv_index}_{question_index}"
            recalled = await memory.recall(workspace.id, conversation.id, token, top_k=5)
            recall_hits += int(bool(recalled))
            fact_hits += int(bool(recalled) and token in recalled[0].summary)
    assert recall_hits / total >= 0.90
    assert fact_hits / total >= 0.90
