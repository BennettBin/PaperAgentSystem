"""Persistence boundary for append-only Evidence Blackboard state."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from backend.core.domain.blackboard import BlackboardEntry, BlackboardEvent


class BlackboardRepository(ABC):
    @abstractmethod
    async def append(
        self, entry: BlackboardEntry, *, expected_version: int
    ) -> BlackboardEntry: ...

    @abstractmethod
    async def list_active(self, workspace_id: str, task_id: str) -> list[BlackboardEntry]: ...

    @abstractmethod
    async def list_events(self, workspace_id: str, task_id: str) -> list[BlackboardEvent]: ...

    @abstractmethod
    async def invalidate_source(
        self, workspace_id: str, source_type: str, source_id: str
    ) -> int: ...

    @staticmethod
    def rebuild(events: Sequence[BlackboardEvent]) -> dict[str, BlackboardEntry]:
        return {event.entry.entry_id: event.entry for event in events}
