import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.core.domain.conversation import Conversation, Message
from backend.core.domain.user import User, Workspace
from backend.core.ports.llm_client import LLMClient
from backend.infrastructure.fake.llm_clients import FakeEmbeddingClient
from backend.infrastructure.postgres.models import Base, MemorySegmentModel
from backend.infrastructure.postgres.repositories import (
    SqlAlchemyConversationRepository,
    SqlAlchemyMessageRepository,
    SqlAlchemyUserRepository,
    SqlAlchemyWorkspaceRepository,
)
from backend.memory.short_term import ShortTermMemoryService
from backend.memory.summarizer import StructuredMemorySummarizer


class RecordingSummaryLLM(LLMClient):
    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def generate(self, prompt, **kwargs):
        return ""

    async def generate_with_schema(self, prompt, **kwargs):
        self.prompts.append(prompt)
        payload = json.loads(prompt.split("\n", 1)[1])
        previous = json.loads(payload["previous_summary"]) if payload["previous_summary"] else {}
        contents = [item["content"] for item in payload["new_messages"]]
        topics = list(dict.fromkeys([*previous.get("topics", []), *contents]))
        return json.dumps(
            {
                "topics": topics,
                "user_goals": topics,
                "decisions": previous.get("decisions", []),
                "referenced_files": [],
                "open_questions": [],
                "source_message_ids": [],
            }
        )


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
        ShortTermMemoryService(
            factory,
            FakeEmbeddingClient(),
            summarizer=StructuredMemorySummarizer(RecordingSummaryLLM()),
            recent_window=12,
            segment_size=6,
        ),
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
    for index in range(20):
        message = Message.create_user_message(
            conversation.id, f"historical fact token{index} value{index}"
        )
        await messages.save(message)
        created.append(message)
    session.commit()

    assert len(memory.recent_messages(workspace.id, conversation.id)) == 12
    segment_id = await memory.summarize_if_needed(workspace.id, conversation.id)
    assert segment_id
    recalled = await memory.recall(workspace.id, conversation.id, "token5 value5", top_k=5)
    recalled_segment_id = recalled[0].segment_id
    assert len(recalled[0].source_messages) == 6
    assert any(item["message_id"] == str(created[5].id) for item in recalled[0].source_messages)
    with context[1]() as verification:
        segments = list(
            verification.query(MemorySegmentModel)
            .filter(MemorySegmentModel.invalidated_at.is_(None))
            .order_by(MemorySegmentModel.source_start_at)
        )
        assert [len(item.source_message_ids) for item in segments] == [6, 2]
        assert len(
            {
                message_id
                for segment in segments
                for message_id in segment.source_message_ids
            }
        ) == 8

    await messages.delete(created[5].id, workspace.id)
    assert memory.invalidate_for_message(str(created[5].id), workspace.id) == 1
    session.commit()
    after_delete = await memory.recall(workspace.id, conversation.id, "token5")
    assert all(
        str(created[5].id)
        not in {item["message_id"] for item in recall.source_messages}
        for recall in after_delete
    )
    rebuilt = await memory.summarize_if_needed(workspace.id, conversation.id)
    assert rebuilt and rebuilt != recalled_segment_id


@pytest.mark.asyncio
async def test_segment_identity_is_stable_when_messages_leave_recent_window(context):
    session, factory, users, workspaces, conversations, messages, memory = context
    user = User.create("stable@example.com", "Stable")
    await users.save(user)
    workspace = Workspace.create(user.id, "stable")
    await workspaces.save(workspace)
    conversation = Conversation.create(workspace.id, user.id, "Stable segments")
    await conversations.save(conversation)
    created = []
    for index in range(13):
        message = Message.create_user_message(conversation.id, f"message-{index}")
        await messages.save(message)
        created.append(message)
    session.commit()

    segment_id = await memory.summarize_if_needed(workspace.id, conversation.id)
    assert segment_id
    for index in range(13, 18):
        await messages.save(
            Message.create_user_message(conversation.id, f"message-{index}")
        )
    session.commit()

    assert await memory.summarize_if_needed(workspace.id, conversation.id) == segment_id
    with factory() as verification:
        segment = verification.get(MemorySegmentModel, segment_id)
        assert segment is not None
        assert segment.source_message_ids == [str(item.id) for item in created[:6]]


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
        for question_index in range(20):
            content = (
                f"project{conv_index} question{question_index} "
                f"answer fact{conv_index}_{question_index}"
            )
            await messages.save(Message.create_user_message(conversation.id, content))
        session.commit()
        await memory.summarize_if_needed(workspace.id, conversation.id)
        for question_index in range(8):
            total += 1
            token = f"fact{conv_index}_{question_index}"
            recalled = await memory.recall(workspace.id, conversation.id, token, top_k=5)
            recall_hits += int(bool(recalled))
            fact_hits += int(bool(recalled) and token in recalled[0].summary)
    assert recall_hits / total >= 0.90
    assert fact_hits / total >= 0.90
