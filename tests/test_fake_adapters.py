from io import BytesIO

import pytest

from apps.worker.fake_queue import FakeTaskQueue
from core.domain.conversation import Conversation
from core.domain.ids import UserId, WorkspaceId
from infrastructure.fake.adapters import (
    FakeClaimVerifier,
    FakeDocumentParser,
    FakeEventPublisher,
    FakeModelRegistry,
    FakeObjectStore,
    FakeRetriever,
    FakeSandboxExecutor,
    FakeSkillDefinition,
    FakeSkillRegistry,
    FakeToolDefinition,
    FakeToolRegistry,
)
from infrastructure.fake.bundle import FakeAdapterBundle
from infrastructure.fake.control import FakeControl, FaultMode
from infrastructure.fake.llm_clients import FakeEmbeddingClient, FakeLLMClient, FakeRerankerClient
from infrastructure.fake.observability import FakeTraceWriter
from infrastructure.fake.repositories import (
    FakeConversationRepository,
    FakeMessageRepository,
    FakeTaskRepository,
)


@pytest.mark.asyncio
async def test_fake_conversation_repository():
    """Test FakeConversationRepository save and find operations"""
    repo = FakeConversationRepository()
    workspace_id = WorkspaceId.generate()
    user_id = UserId.generate()
    conv = Conversation.create(
        workspace_id=workspace_id,
        user_id=user_id,
        title="Test",
    )
    await repo.save(conv)
    found = await repo.find_by_id(conv.id, workspace_id)
    assert found is not None
    assert found.title == "Test"


@pytest.mark.asyncio
async def test_fake_message_repository():
    """Test FakeMessageRepository operations"""
    repo = FakeMessageRepository()
    assert isinstance(repo, FakeMessageRepository)


@pytest.mark.asyncio
async def test_fake_task_repository():
    """Test FakeTaskRepository operations"""
    repo = FakeTaskRepository()
    assert isinstance(repo, FakeTaskRepository)


@pytest.mark.asyncio
async def test_fake_llm_client():
    """Test FakeLLMClient generate"""
    client = FakeLLMClient()
    response = await client.generate("test prompt")
    assert "test prompt" in response
    assert client.call_count == 1


@pytest.mark.asyncio
async def test_fake_llm_client_failure():
    """Test FakeLLMClient with failure mode"""
    client = FakeLLMClient(should_fail=True)
    with pytest.raises(RuntimeError):
        await client.generate("test prompt")


@pytest.mark.asyncio
async def test_fake_embedding_client():
    """Test FakeEmbeddingClient embed"""
    client = FakeEmbeddingClient()
    embedding = await client.embed("test")
    assert len(embedding) > 0
    assert isinstance(embedding[0], float)


@pytest.mark.asyncio
async def test_fake_reranker_client():
    """Test FakeRerankerClient rerank"""
    client = FakeRerankerClient()
    results = await client.rerank("query", ["doc1", "doc2"], top_k=2)
    assert len(results) == 2
    assert results[0][0] == 0


@pytest.mark.asyncio
async def test_fake_object_store():
    """Test FakeObjectStore upload and download"""
    store = FakeObjectStore()
    data = b"test content"
    key = await store.upload("test-key", data, "text/plain")
    assert key == "test-key"

    exists = await store.exists("test-key")
    assert exists is True

    downloaded = await store.download("test-key")
    assert downloaded == b"test content"

    url = await store.get_temporary_url("test-key")
    assert "fake-minio" in url


@pytest.mark.asyncio
async def test_fake_event_publisher():
    """Test FakeEventPublisher publish"""
    pub = FakeEventPublisher()
    await pub.publish("test_event", {"data": "test"}, channel="task-1")
    assert len(pub.events) == 1
    assert len(await pub.subscribe("task-1")) == 1


@pytest.mark.asyncio
async def test_fake_tool_registry():
    """Test FakeToolRegistry register and get"""
    registry = FakeToolRegistry()
    tool = FakeToolDefinition(
        name="test_tool",
        description="Test tool",
        parameters_schema={"type": "object"},
    )
    await registry.register(tool)

    found = await registry.get("test_tool")
    assert found is not None
    assert found.name == "test_tool"

    all_tools = await registry.list_all()
    assert len(all_tools) == 1


@pytest.mark.asyncio
async def test_fake_skill_registry():
    """Test FakeSkillRegistry register and get"""
    registry = FakeSkillRegistry()
    skill = FakeSkillDefinition(
        name="test_skill",
        description="Test skill",
        required_tools=[],
        model_profile="development",
    )
    await registry.register(skill)

    found = await registry.get("test_skill")
    assert found is not None
    assert found.name == "test_skill"


@pytest.mark.asyncio
async def test_fake_model_registry():
    """Test FakeModelRegistry get_profile"""
    registry = FakeModelRegistry()
    profile = await registry.get_profile("development")
    assert profile is not None
    assert profile.name == "development"
    assert profile.context_length == 4096


@pytest.mark.asyncio
async def test_fake_document_parser():
    """Test FakeDocumentParser parse"""
    parser = FakeDocumentParser()
    result = await parser.parse(b"fake", "test.pdf")
    assert "text" in result
    assert "chunks" in result
    assert await parser.supports_format("test.pdf")
    assert not await parser.supports_format("test.xyz")


@pytest.mark.asyncio
async def test_fake_retriever():
    """Test FakeRetriever search"""
    retriever = FakeRetriever()
    results = await retriever.search("query", top_k=5)
    assert len(results) > 0
    assert "doc_id" in results[0]


@pytest.mark.asyncio
async def test_fake_claim_verifier():
    """Test FakeClaimVerifier verify_claim"""
    verifier = FakeClaimVerifier()
    result = await verifier.verify_claim("claim", ["evidence1"])
    assert "is_supported" in result
    assert result["is_supported"] is True


@pytest.mark.asyncio
async def test_fake_sandbox_executor():
    """Test FakeSandboxExecutor execute_code"""
    executor = FakeSandboxExecutor()
    result = await executor.execute_code("print('hello')", "python")
    assert "error" in result
    assert result["success"] is False


@pytest.mark.asyncio
async def test_fake_trace_writer():
    """Test FakeTraceWriter write_trace"""
    writer = FakeTraceWriter()
    await writer.write_trace("trace-1", "span-1", {"key": "value"})
    traces = writer.get_traces()
    assert len(traces) == 1
    assert traces[0]["trace_id"] == "trace-1"


def test_fake_task_queue():
    """Test FakeTaskQueue instantiation"""
    queue = FakeTaskQueue()
    assert queue is not None
    assert hasattr(queue, "handlers")


@pytest.mark.asyncio
async def test_fake_repositories_workspace_isolation():
    """Verify Workspace isolation across all repositories"""
    conv_repo = FakeConversationRepository()
    ws1 = WorkspaceId.generate()
    ws2 = WorkspaceId.generate()
    user_id = UserId.generate()

    conv1 = Conversation.create(workspace_id=ws1, user_id=user_id, title="Conv1")
    conv2 = Conversation.create(workspace_id=ws2, user_id=user_id, title="Conv2")

    await conv_repo.save(conv1)
    await conv_repo.save(conv2)

    # Should only find conv1 in ws1
    found_in_ws1 = await conv_repo.find_by_id(conv1.id, ws1)
    assert found_in_ws1 is not None

    # Should not find conv1 in ws2
    not_found_in_ws2 = await conv_repo.find_by_id(conv1.id, ws2)
    assert not_found_in_ws2 is None


@pytest.mark.asyncio
async def test_object_store_stream_operations():
    """Test FakeObjectStore stream operations"""
    store = FakeObjectStore()
    data = BytesIO(b"test stream content")
    key = await store.upload_stream("stream-key", data, "text/plain")
    assert key == "stream-key"

    downloaded_stream = await store.download_stream("stream-key")
    assert downloaded_stream.getvalue() == b"test stream content"

    await store.delete("stream-key")
    assert not await store.exists("stream-key")


def test_fake_adapter_bundle_covers_stage_b_ports():
    bundle = FakeAdapterBundle.create()
    expected = {
        "conversations",
        "messages",
        "tasks",
        "files",
        "users",
        "workspaces",
        "memory",
        "object_store",
        "task_queue",
        "events",
        "llm",
        "embeddings",
        "reranker",
        "parser",
        "retriever",
        "claim_verifier",
        "sandbox",
        "tools",
        "skills",
        "models",
        "traces",
    }
    assert all(getattr(bundle, name) is not None for name in expected)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "error_type"),
    [
        (FaultMode.FAILURE, RuntimeError),
        (FaultMode.TIMEOUT, TimeoutError),
    ],
)
async def test_fake_control_fault_injection(mode, error_type):
    control = FakeControl(mode=mode)
    with pytest.raises(error_type):
        await control.checkpoint("contract-test")


@pytest.mark.asyncio
async def test_fake_control_partial_failure_is_deterministic():
    control = FakeControl(mode=FaultMode.PARTIAL)
    await control.checkpoint("partial")
    assert control.is_partial is True
