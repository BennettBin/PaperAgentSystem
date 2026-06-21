import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.errors import ErrorCode, ProjectError
from infrastructure.fake.adapters import FakeObjectStore
from infrastructure.fake.llm_clients import FakeEmbeddingClient
from infrastructure.fake.observability import FakeTraceWriter
from infrastructure.postgres.models import Base
from tool_runtime import (
    InMemoryDataRefStore,
    InMemoryIdempotencyStore,
    ToolContext,
    ToolRegistry,
    ToolRuntime,
)
from tool_runtime.workspace_tools import (
    InMemoryWorkspaceAuditWriter,
    register_workspace_tools,
)
from workspace.search import WorkspaceSearchService
from workspace.service import WorkspaceService


@pytest.fixture
def services(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'tools.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    object_store = FakeObjectStore()
    workspace = WorkspaceService(tmp_path / "mount", factory, object_store)
    search = WorkspaceSearchService(factory, FakeEmbeddingClient())
    registry = ToolRegistry()
    audit = InMemoryWorkspaceAuditWriter()
    register_workspace_tools(registry, workspace, search, audit)
    runtime = ToolRuntime(
        registry,
        idempotency_store=InMemoryIdempotencyStore(),
        data_ref_store=InMemoryDataRefStore(),
        trace_writer=FakeTraceWriter(),
        max_inline_bytes=4096,
    )
    return workspace, search, object_store, audit, runtime


def context(workspace_id="ws-1", task_id="task-1"):
    tools = {
        "list_workspace_files",
        "search_workspace_files",
        "read_workspace_entry",
        "write_workspace_entry",
        "promote_workspace_entry",
        "save_artifact",
    }
    return ToolContext(
        workspace_id=workspace_id,
        user_id="user-1",
        conversation_id="conv-1",
        task_id=task_id,
        trace_id="trace-1",
        permissions=frozenset(
            {"workspace:read", "workspace:write", "workspace:promote"}
        ),
        allowed_tools=frozenset(tools),
    )


@pytest.mark.asyncio
async def test_workspace_tool_round_trip_search_and_listing(services) -> None:
    workspace, search, _, _, runtime = services
    written = await runtime.invoke(
        "write_workspace_entry",
        {
            "relative_path": "outputs/result.md",
            "content": "bayesian calibration result",
            "content_type": "text/markdown",
        },
        context(),
        "write-1",
    )
    entry_id = written.output["entry"]["workspace_entry_id"]
    await search.index(entry_id, "bayesian calibration result")

    listed = await runtime.invoke("list_workspace_files", {}, context(), "list-1")
    found = await runtime.invoke(
        "search_workspace_files",
        {"query": "calibration"},
        context(),
        "search-1",
    )
    read = await runtime.invoke(
        "read_workspace_entry",
        {"workspace_entry_id": entry_id},
        context(),
        "read-1",
    )

    assert listed.output["entries"][0]["workspace_entry_id"] == entry_id
    assert found.output["entries"][0]["workspace_entry_id"] == entry_id
    assert read.output["content"] == "bayesian calibration result"
    assert workspace.get_entry(entry_id, "ws-1", "conv-1", task_id="task-1")


@pytest.mark.asyncio
async def test_cross_workspace_and_cross_task_entries_are_denied(services) -> None:
    workspace, _, _, _, runtime = services
    foreign = await workspace.write_entry(
        "ws-2",
        "conv-1",
        "outputs/private.md",
        b"private",
        "text/markdown",
        task_id="task-2",
    )

    with pytest.raises(ProjectError) as exc:
        await runtime.invoke(
            "read_workspace_entry",
            {"workspace_entry_id": foreign.entry_id},
            context(),
            "read-foreign",
        )

    assert exc.value.code is ErrorCode.PERMISSION_DENIED


@pytest.mark.asyncio
async def test_promote_has_audit_and_artifact_uses_object_store(services) -> None:
    workspace, _, object_store, audit, runtime = services
    entry = await workspace.write_entry(
        "ws-1",
        "conv-1",
        "outputs/result.md",
        b"result",
        "text/markdown",
        task_id="task-1",
    )
    promoted = await runtime.invoke(
        "promote_workspace_entry",
        {"workspace_entry_id": entry.entry_id, "destination": "shared"},
        context(),
        "promote-1",
    )
    artifact = await runtime.invoke(
        "save_artifact",
        {"filename": "report.md", "content": "x" * 500},
        context(),
        "artifact-1",
    )

    assert promoted.output["entry"]["relative_path"].startswith("shared/")
    assert audit.events[0]["source_entry_id"] == entry.entry_id
    artifact_entry = workspace.get_entry(
        artifact.output["entry"]["workspace_entry_id"],
        "ws-1",
        "conv-1",
    )
    assert artifact_entry.object_key in object_store.objects
