import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.core.domain.conversation import Conversation, Message
from backend.core.domain.user import User, Workspace
from backend.core.ports.llm_client import LLMClient
from backend.infrastructure.fake.llm_clients import FakeEmbeddingClient
from backend.infrastructure.postgres.models import Base, ConversationSummaryModel
from backend.infrastructure.postgres.repositories import (
    SqlAlchemyConversationRepository,
    SqlAlchemyMessageRepository,
    SqlAlchemyUserRepository,
    SqlAlchemyWorkspaceRepository,
)
from backend.memory.long_term import LongTermMemoryService
from backend.memory.summarizer import StructuredMemorySummarizer
from backend.workspace.search import WorkspaceSearchService
from backend.workspace.service import WorkspaceService


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
                "referenced_files": previous.get("referenced_files", []),
                "open_questions": previous.get("open_questions", []),
                "source_message_ids": [],
            }
        )


@pytest.fixture
def context(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'long.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    session = Session(engine, expire_on_commit=False)
    embeddings = FakeEmbeddingClient()
    summary_llm = RecordingSummaryLLM()
    return (
        session,
        factory,
        SqlAlchemyUserRepository(session),
        SqlAlchemyWorkspaceRepository(session),
        SqlAlchemyConversationRepository(session),
        SqlAlchemyMessageRepository(session),
        WorkspaceService(tmp_path / "mount", factory),
        WorkspaceSearchService(factory, embeddings),
        LongTermMemoryService(
            factory,
            embeddings,
            summarizer=StructuredMemorySummarizer(summary_llm),
        ),
        summary_llm,
    )


@pytest.mark.asyncio
async def test_cross_conversation_recall_file_link_and_preferences(context):
    session, _, users, workspaces, conversations, messages, workspace_service, search, memory, _ = context
    user = User.create("long@example.com", "Long")
    await users.save(user)
    workspace = Workspace.create(user.id, "long")
    await workspaces.save(workspace)
    targets = []
    for index in range(20):
        conversation = Conversation.create(workspace.id, user.id, f"Research {index}")
        await conversations.save(conversation)
        token = f"crossfact{index}"
        message = Message.create_user_message(
            conversation.id, f"historical finding {token}"
        )
        await messages.save(message)
        targets.append((conversation, token))
    session.commit()
    for conversation, _ in targets:
        await memory.summarize_conversation(str(workspace.id), str(conversation.id))

    hits = 0
    for conversation, token in targets:
        results = await memory.search(str(workspace.id), token, top_k=5)
        hits += int(results[0].conversation_id == str(conversation.id))
    assert hits / len(targets) >= 0.85

    entry = await workspace_service.write_entry(
        str(workspace.id),
        str(targets[0][0].id),
        "shared/legacy-script.py",
        b"rare historical optimizer script",
        "text/x-python",
        source_type="tool",
        source_id="tool-old",
    )
    await search.index(entry.entry_id, "rare historical optimizer script")
    file_results = await memory.search(str(workspace.id), "rare optimizer", top_k=5)
    assert any(item.id == entry.entry_id for item in file_results)

    with pytest.raises(ValueError):
        memory.save_preference(
            str(workspace.id), str(user.id), "style", "concise", "style", explicit=False
        )
    preference_id = memory.save_preference(
        str(workspace.id), str(user.id), "style", "concise", "style", explicit=True
    )
    assert memory.list_preferences(str(workspace.id), str(user.id)) == {
        "style": "concise"
    }
    assert memory.forget_preference(preference_id, str(workspace.id))
    assert memory.list_preferences(str(workspace.id), str(user.id)) == {}


@pytest.mark.asyncio
async def test_forget_removes_summary_and_historical_file(context):
    session, _, users, workspaces, conversations, messages, workspace_service, search, memory, _ = context
    user = User.create("forget@example.com", "Forget")
    await users.save(user)
    workspace = Workspace.create(user.id, "forget")
    await workspaces.save(workspace)
    conversation = Conversation.create(workspace.id, user.id, "Delete me")
    await conversations.save(conversation)
    await messages.save(
        Message.create_user_message(conversation.id, "forgettabletoken")
    )
    session.commit()
    await memory.summarize_conversation(str(workspace.id), str(conversation.id))
    entry = await workspace_service.write_entry(
        str(workspace.id),
        str(conversation.id),
        "shared/forgotten.md",
        b"forgettablefiletoken",
        "text/markdown",
        source_type="message",
        source_id="message-forget",
    )
    await search.index(entry.entry_id, "forgettablefiletoken")
    assert await memory.search(str(workspace.id), "forgettabletoken")
    assert await memory.search(str(workspace.id), "forgettablefiletoken")
    memory.forget_conversation(str(workspace.id), str(conversation.id))
    assert await memory.search(str(workspace.id), "forgettabletoken") == []
    assert await memory.search(str(workspace.id), "forgettablefiletoken") == []


@pytest.mark.asyncio
async def test_conversation_summary_updates_from_old_summary_and_only_new_messages(context):
    (
        session,
        factory,
        users,
        workspaces,
        conversations,
        messages,
        _,
        _,
        memory,
        summary_llm,
    ) = context
    user = User.create("incremental@example.com", "Incremental")
    await users.save(user)
    workspace = Workspace.create(user.id, "incremental")
    await workspaces.save(workspace)
    conversation = Conversation.create(workspace.id, user.id, "Incremental summary")
    await conversations.save(conversation)
    first = Message.create_user_message(conversation.id, "first-secret-message")
    await messages.save(first)
    session.commit()

    await memory.summarize_conversation(str(workspace.id), str(conversation.id))
    second = Message.create_user_message(conversation.id, "second-new-message")
    await messages.save(second)
    session.commit()
    await memory.summarize_conversation(str(workspace.id), str(conversation.id))

    assert len(summary_llm.prompts) == 2
    update_payload = json.loads(summary_llm.prompts[1].split("\n", 1)[1])
    assert update_payload["previous_summary"]
    assert [item["content"] for item in update_payload["new_messages"]] == [
        "second-new-message"
    ]
    with factory() as verification:
        stored = verification.get(ConversationSummaryModel, str(conversation.id))
        assert stored is not None
        payload = json.loads(stored.summary)
        assert payload["source_message_ids"] == [str(first.id), str(second.id)]
