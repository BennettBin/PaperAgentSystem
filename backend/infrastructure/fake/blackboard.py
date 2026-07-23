"""Deterministic Blackboard Adapter used by contract and component tests."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal
from uuid import uuid4

from backend.core.domain.blackboard import BlackboardEntry, BlackboardEvent
from backend.core.errors import ErrorCode, ProjectError
from backend.core.ports.blackboard import BlackboardRepository


class InMemoryBlackboardRepository(BlackboardRepository):
    def __init__(self) -> None:
        self._current: dict[tuple[str, str, str], BlackboardEntry] = {}
        self._events: list[BlackboardEvent] = []

    async def append(
        self, entry: BlackboardEntry, *, expected_version: int
    ) -> BlackboardEntry:
        key = (entry.workspace_id, entry.task_id, entry.entry_id)
        current = self._current.get(key)
        actual = 0 if current is None else current.version
        if actual != expected_version or entry.version != expected_version + 1:
            raise ProjectError(
                ErrorCode.FAILED_PRECONDITION,
                "Blackboard optimistic version conflict",
                {"entry_id": entry.entry_id, "expected": expected_version, "actual": actual},
            )
        event_type: Literal["created", "updated"] = (
            "created" if current is None else "updated"
        )
        self._current[key] = entry
        self._events.append(
            BlackboardEvent(event_id=str(uuid4()), event_type=event_type, entry=entry)
        )
        return entry

    async def list_active(self, workspace_id: str, task_id: str) -> list[BlackboardEntry]:
        return sorted(
            (
                entry
                for (workspace, task, _), entry in self._current.items()
                if workspace == workspace_id and task == task_id and entry.invalidated_at is None
            ),
            key=lambda entry: entry.entry_id,
        )

    async def list_events(self, workspace_id: str, task_id: str) -> list[BlackboardEvent]:
        return [
            event
            for event in self._events
            if event.entry.workspace_id == workspace_id and event.entry.task_id == task_id
        ]

    async def invalidate_source(
        self, workspace_id: str, source_type: str, source_id: str
    ) -> int:
        if source_type not in {"file", "message"}:
            raise ProjectError(ErrorCode.INVALID_ARGUMENT, "Unsupported Blackboard source type")
        count = 0
        for key, entry in list(self._current.items()):
            source_value = entry.source.file_id if source_type == "file" else entry.source.message_id
            if key[0] != workspace_id or source_value != source_id or entry.invalidated_at:
                continue
            invalidated = entry.invalidate()
            self._current[key] = invalidated
            self._events.append(
                BlackboardEvent(
                    event_id=str(uuid4()), event_type="invalidated", entry=invalidated
                )
            )
            count += 1
        return count

    @staticmethod
    def rebuild(events: Sequence[BlackboardEvent]) -> dict[str, BlackboardEntry]:
        return BlackboardRepository.rebuild(events)
