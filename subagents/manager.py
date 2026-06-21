"""Sub Agent orchestration with bounded concurrency and partial results."""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Awaitable, Callable, Protocol
from uuid import uuid4

from celery import group  # type: ignore[import-untyped]
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from core.errors import ErrorCode, ProjectError
from core.ports.observability import TraceWriter
from infrastructure.postgres.models import SubAgentRunModel
from subagents.paper_reader import (
    PaperReaderAgent,
    PaperReaderRequest,
    PaperReaderResult,
    PaperReaderScope,
)


class ChildStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class ChildTask:
    child_task_id: str
    parent_task_id: str
    workspace_id: str
    file_id: str
    agent_name: str = "paper_reader_agent"
    depth: int = 1
    status: ChildStatus = ChildStatus.QUEUED
    result: dict[str, Any] | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class SubAgentBatchResult:
    parent_task_id: str
    completed: tuple[ChildTask, ...]
    failed: tuple[ChildTask, ...]
    cancelled: tuple[ChildTask, ...]


class SubAgentStore(Protocol):
    async def save(self, task: ChildTask) -> None: ...
    async def list_by_parent(self, parent_task_id: str) -> list[ChildTask]: ...


class InMemorySubAgentStore:
    def __init__(self) -> None:
        self.tasks: dict[str, ChildTask] = {}

    async def save(self, task: ChildTask) -> None:
        self.tasks[task.child_task_id] = task

    async def list_by_parent(self, parent_task_id: str) -> list[ChildTask]:
        return [task for task in self.tasks.values() if task.parent_task_id == parent_task_id]


class SqlAlchemySubAgentStore:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sessions = session_factory

    async def save(self, task: ChildTask) -> None:
        with self._sessions() as session:
            model = session.get(SubAgentRunModel, task.child_task_id)
            if model is None:
                model = SubAgentRunModel(
                    child_task_id=task.child_task_id,
                    parent_task_id=task.parent_task_id,
                    workspace_id=task.workspace_id,
                    agent_name=task.agent_name,
                    file_id=task.file_id,
                    depth=task.depth,
                    status=task.status.value,
                )
            model.status = task.status.value
            model.result = task.result
            model.error = task.error
            session.add(model)
            session.commit()

    async def list_by_parent(self, parent_task_id: str) -> list[ChildTask]:
        with self._sessions() as session:
            models = session.scalars(
                select(SubAgentRunModel).where(
                    SubAgentRunModel.parent_task_id == parent_task_id
                )
            ).all()
            return [
                ChildTask(
                    child_task_id=model.child_task_id,
                    parent_task_id=model.parent_task_id,
                    workspace_id=model.workspace_id,
                    file_id=model.file_id,
                    agent_name=model.agent_name,
                    depth=model.depth,
                    status=ChildStatus(model.status),
                    result=model.result,
                    error=model.error,
                )
                for model in models
            ]


class CeleryGroupScheduler:
    """Production scheduler: all children are submitted as one Celery Group."""

    def __init__(self, celery_app: Any, task_name: str = "paperagent.sub_agent") -> None:
        self._app = celery_app
        self._task_name = task_name
        self._groups: dict[str, Any] = {}

    def enqueue(self, tasks: list[ChildTask]) -> str:
        signatures = [
            self._app.signature(
                self._task_name,
                kwargs={
                    "child_task_id": task.child_task_id,
                    "parent_task_id": task.parent_task_id,
                    "workspace_id": task.workspace_id,
                    "file_id": task.file_id,
                    "depth": task.depth,
                },
                queue="sub_agent",
            )
            for task in tasks
        ]
        result = group(signatures).apply_async()
        group_id = str(result.id)
        self._groups[group_id] = result
        return group_id

    def cancel(self, group_id: str) -> None:
        result = self._groups.get(group_id)
        if result is not None:
            result.revoke(terminate=False)
            return
        self._app.control.revoke(group_id, terminate=False)


CancellationCheck = Callable[[str], bool | Awaitable[bool]]


class SubAgentManager:
    def __init__(
        self,
        paper_reader: PaperReaderAgent,
        store: SubAgentStore,
        trace_writer: TraceWriter,
        *,
        max_concurrency: int = 4,
        is_parent_cancelled: CancellationCheck | None = None,
        celery_scheduler: CeleryGroupScheduler | None = None,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")
        self._reader = paper_reader
        self._store = store
        self._traces = trace_writer
        self._max_concurrency = max_concurrency
        self._is_parent_cancelled = is_parent_cancelled or (lambda _: False)
        self._celery_scheduler = celery_scheduler
        self._celery_groups: dict[str, str] = {}

    async def enqueue_paper_readers(
        self,
        *,
        parent_task_id: str,
        workspace_id: str,
        file_ids: list[str],
        parent_depth: int = 0,
    ) -> str:
        if self._celery_scheduler is None:
            raise ProjectError(ErrorCode.UNAVAILABLE, "Celery Group scheduler is unavailable")
        tasks = self._new_tasks(parent_task_id, workspace_id, file_ids, parent_depth)
        for task in tasks:
            await self._store.save(task)
        group_id = self._celery_scheduler.enqueue(tasks)
        self._celery_groups[parent_task_id] = group_id
        return group_id

    async def run_paper_readers(
        self,
        *,
        parent_task_id: str,
        workspace_id: str,
        file_ids: list[str],
        trace_id: str,
        parent_depth: int = 0,
    ) -> SubAgentBatchResult:
        tasks = self._new_tasks(parent_task_id, workspace_id, file_ids, parent_depth)
        for task in tasks:
            await self._store.save(task)
        semaphore = asyncio.Semaphore(self._max_concurrency)

        async def run(task: ChildTask) -> ChildTask:
            if await self._cancelled(parent_task_id):
                cancelled = replace(task, status=ChildStatus.CANCELLED)
                await self._store.save(cancelled)
                return cancelled
            async with semaphore:
                if await self._cancelled(parent_task_id):
                    cancelled = replace(task, status=ChildStatus.CANCELLED)
                    await self._store.save(cancelled)
                    return cancelled
                running = replace(task, status=ChildStatus.RUNNING)
                await self._store.save(running)
                try:
                    result = await self._reader.execute(
                        PaperReaderScope(
                            workspace_id=workspace_id,
                            parent_task_id=parent_task_id,
                            child_task_id=task.child_task_id,
                            assigned_file_id=task.file_id,
                            trace_id=trace_id,
                            depth=task.depth,
                        ),
                        PaperReaderRequest(file_id=task.file_id),
                    )
                    completed = replace(
                        task,
                        status=ChildStatus.COMPLETED,
                        result=_result_dict(result),
                    )
                    await self._store.save(completed)
                    return completed
                except Exception as exc:
                    failed = replace(task, status=ChildStatus.FAILED, error=str(exc))
                    await self._store.save(failed)
                    return failed

        results = await asyncio.gather(*(run(task) for task in tasks))
        completed = tuple(item for item in results if item.status is ChildStatus.COMPLETED)
        failed = tuple(item for item in results if item.status is ChildStatus.FAILED)
        cancelled = tuple(item for item in results if item.status is ChildStatus.CANCELLED)
        await self._traces.write_trace(
            trace_id,
            "subagent.group",
            {
                "parent_task_id": parent_task_id,
                "child_task_ids": [task.child_task_id for task in tasks],
                "max_concurrency": self._max_concurrency,
                "completed": len(completed),
                "failed": len(failed),
                "cancelled": len(cancelled),
            },
        )
        return SubAgentBatchResult(parent_task_id, completed, failed, cancelled)

    async def cancel_parent(self, parent_task_id: str) -> int:
        group_id = self._celery_groups.get(parent_task_id)
        if group_id and self._celery_scheduler:
            self._celery_scheduler.cancel(group_id)
        tasks = await self._store.list_by_parent(parent_task_id)
        cancelled = 0
        for task in tasks:
            if task.status is ChildStatus.QUEUED:
                await self._store.save(replace(task, status=ChildStatus.CANCELLED))
                cancelled += 1
        return cancelled

    @staticmethod
    def _new_tasks(
        parent_task_id: str,
        workspace_id: str,
        file_ids: list[str],
        parent_depth: int,
    ) -> list[ChildTask]:
        if parent_depth >= 1:
            raise ProjectError(
                ErrorCode.FAILED_PRECONDITION,
                "Sub Agent nesting depth cannot exceed one",
            )
        return [
            ChildTask(
                child_task_id=uuid4().hex,
                parent_task_id=parent_task_id,
                workspace_id=workspace_id,
                file_id=file_id,
                depth=parent_depth + 1,
            )
            for file_id in file_ids
        ]

    async def _cancelled(self, parent_task_id: str) -> bool:
        value = self._is_parent_cancelled(parent_task_id)
        if inspect.isawaitable(value):
            return bool(await value)
        return bool(value)


def _result_dict(result: PaperReaderResult) -> dict[str, Any]:
    return {
        "child_task_id": result.child_task_id,
        "file_id": result.file_id,
        "model_profile": result.model_profile,
        "card": result.card.model_dump(mode="json"),
        "duration_ms": result.duration_ms,
    }
