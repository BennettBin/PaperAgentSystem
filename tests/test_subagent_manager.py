import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from infrastructure.fake.observability import FakeTraceWriter
from infrastructure.postgres.models import Base
from subagents.manager import (
    CeleryGroupScheduler,
    ChildStatus,
    InMemorySubAgentStore,
    SqlAlchemySubAgentStore,
    SubAgentManager,
)
from subagents.paper_reader import PaperReaderAgent


def card(title: str) -> dict:
    return {
        "title": title,
        "research_question": "RQ",
        "methodology": "Method",
        "datasets": [],
        "metrics": [],
        "results": [],
        "contributions": [],
        "limitations": [],
        "evidence": [],
        "missing_fields": [],
    }


class ConcurrentBackend:
    def __init__(self, failures: set[str] | None = None) -> None:
        self.failures = failures or set()
        self.running = 0
        self.max_running = 0

    async def read(self, **kwargs):
        file_id = kwargs["file_id"]
        self.running += 1
        self.max_running = max(self.max_running, self.running)
        await asyncio.sleep(0.01)
        self.running -= 1
        if file_id in self.failures:
            raise RuntimeError(f"failed: {file_id}")
        return card(file_id)


@pytest.mark.asyncio
async def test_multi_paper_tasks_run_concurrently_with_partial_failure() -> None:
    backend = ConcurrentBackend({"file-2"})
    store = InMemorySubAgentStore()
    manager = SubAgentManager(
        PaperReaderAgent(backend, FakeTraceWriter()),
        store,
        FakeTraceWriter(),
        max_concurrency=2,
    )

    result = await manager.run_paper_readers(
        parent_task_id="parent-1",
        workspace_id="ws-1",
        file_ids=["file-1", "file-2", "file-3"],
        trace_id="trace-1",
    )

    assert backend.max_running == 2
    assert {item.file_id for item in result.completed} == {"file-1", "file-3"}
    assert {item.file_id for item in result.failed} == {"file-2"}
    assert len(await store.list_by_parent("parent-1")) == 3


@pytest.mark.asyncio
async def test_parent_cancellation_cancels_not_started_children() -> None:
    manager = SubAgentManager(
        PaperReaderAgent(ConcurrentBackend(), FakeTraceWriter()),
        InMemorySubAgentStore(),
        FakeTraceWriter(),
        max_concurrency=1,
        is_parent_cancelled=lambda _: True,
    )

    result = await manager.run_paper_readers(
        parent_task_id="parent-2",
        workspace_id="ws-1",
        file_ids=["file-1", "file-2"],
        trace_id="trace-2",
    )

    assert not result.completed
    assert {item.status for item in result.cancelled} == {ChildStatus.CANCELLED}


@pytest.mark.asyncio
async def test_sql_store_persists_parent_child_relationship(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'subagents.db').as_posix()}")
    Base.metadata.create_all(engine)
    store = SqlAlchemySubAgentStore(sessionmaker(engine, expire_on_commit=False))
    manager = SubAgentManager(
        PaperReaderAgent(ConcurrentBackend(), FakeTraceWriter()),
        store,
        FakeTraceWriter(),
    )

    await manager.run_paper_readers(
        parent_task_id="parent-3",
        workspace_id="ws-1",
        file_ids=["file-1"],
        trace_id="trace-3",
    )

    stored = await store.list_by_parent("parent-3")
    assert stored[0].parent_task_id == "parent-3"
    assert stored[0].status is ChildStatus.COMPLETED


def test_celery_group_scheduler_builds_subagent_group(monkeypatch) -> None:
    calls = []

    class Result:
        id = "group-1"

        def revoke(self, terminate):
            calls.append(("result-revoke", terminate))

    class Group:
        def apply_async(self):
            calls.append("apply_async")
            return Result()

    class App:
        class Control:
            def revoke(self, group_id, terminate):
                calls.append((group_id, terminate))

        control = Control()

        def signature(self, name, kwargs, queue):
            calls.append((name, kwargs["file_id"], queue))
            return kwargs

    monkeypatch.setattr("subagents.manager.group", lambda signatures: Group())
    scheduler = CeleryGroupScheduler(App())
    from subagents.manager import ChildTask

    group_id = scheduler.enqueue(
        [
            ChildTask("c1", "p1", "ws", "f1"),
            ChildTask("c2", "p1", "ws", "f2"),
        ]
    )
    scheduler.cancel(group_id)

    assert group_id == "group-1"
    assert calls[0] == ("paperagent.sub_agent", "f1", "sub_agent")
    assert calls[-1] == ("result-revoke", False)


@pytest.mark.asyncio
async def test_manager_propagates_parent_cancel_to_celery_group() -> None:
    class Scheduler:
        def __init__(self) -> None:
            self.cancelled: list[str] = []

        def enqueue(self, tasks) -> str:
            return "group-parent"

        def cancel(self, group_id: str) -> None:
            self.cancelled.append(group_id)

    scheduler = Scheduler()
    store = InMemorySubAgentStore()
    manager = SubAgentManager(
        PaperReaderAgent(ConcurrentBackend(), FakeTraceWriter()),
        store,
        FakeTraceWriter(),
        celery_scheduler=scheduler,
    )
    await manager.enqueue_paper_readers(
        parent_task_id="parent-4",
        workspace_id="ws-1",
        file_ids=["file-1", "file-2"],
    )

    count = await manager.cancel_parent("parent-4")

    assert count == 2
    assert scheduler.cancelled == ["group-parent"]
    assert all(
        task.status is ChildStatus.CANCELLED
        for task in await store.list_by_parent("parent-4")
    )
