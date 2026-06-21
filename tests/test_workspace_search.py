import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from infrastructure.fake.llm_clients import FakeEmbeddingClient
from infrastructure.postgres.models import Base
from workspace.search import WorkspaceSearchService
from workspace.service import WorkspaceService


@pytest.fixture
def services(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'search.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    workspace = WorkspaceService(tmp_path / "mount", factory)
    search = WorkspaceSearchService(factory, FakeEmbeddingClient())
    return workspace, search


@pytest.mark.asyncio
async def test_old_script_output_same_names_and_source_trace(services):
    workspace, search = services
    script = await workspace.write_entry(
        "ws",
        "old-conv",
        "scripts/analysis.py",
        b"bayesian calibration script",
        "text/x-python",
        task_id="old-task",
        source_type="tool",
        source_id="tool-script",
    )
    output = await workspace.write_entry(
        "ws",
        "old-conv",
        "outputs/result.md",
        b"calibration improved expected error",
        "text/markdown",
        task_id="old-task",
        source_type="message",
        source_id="message-result",
    )
    same_name = await workspace.write_entry(
        "ws",
        "current-conv",
        "outputs/result.md",
        b"unrelated transformer output",
        "text/markdown",
        task_id="current-task",
        source_type="task",
        source_id="current-task",
    )
    await search.index(script.entry_id, "bayesian calibration script")
    await search.index(output.entry_id, "calibration improved expected error")
    await search.index(same_name.entry_id, "unrelated transformer output")

    results = await search.search(
        "ws",
        "bayesian calibration",
        current_conversation_id="current-conv",
        current_task_id="current-task",
    )
    assert results[0].entry_id == script.entry_id
    assert all(result.source_type and result.source_id for result in results)
    named = [result for result in results if result.filename == "result.md"]
    assert len(named) == 2
    assert {result.entry_id for result in named} == {output.entry_id, same_name.entry_id}


@pytest.mark.asyncio
async def test_deletion_invalidates_search_and_location_rate(services):
    workspace, search = services
    entries = []
    for index in range(20):
        entry = await workspace.write_entry(
            "ws",
            f"conv-{index}",
            f"outputs/topic-{index}.md",
            f"unique research token{index}".encode(),
            "text/markdown",
            task_id=f"task-{index}",
            source_type="task",
            source_id=f"task-{index}",
        )
        await search.index(entry.entry_id, f"unique research token{index}")
        entries.append(entry)

    hits = 0
    for index, entry in enumerate(entries):
        results = await search.search(
            "ws",
            f"token{index}",
            current_conversation_id="current",
            current_task_id="current-task",
            limit=1,
        )
        hits += int(results[0].entry_id == entry.entry_id)
    assert hits / len(entries) >= 0.95
    assert search.delete(entries[0].entry_id, "ws")
    after = await search.search(
        "ws",
        "token0",
        current_conversation_id="current",
        current_task_id="current-task",
    )
    assert all(result.entry_id != entries[0].entry_id for result in after)
