"""SQLAlchemy implementation of the append-only Blackboard Port."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal, cast
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from backend.core.domain.blackboard import BlackboardEntry, BlackboardEvent
from backend.core.errors import ErrorCode, ProjectError
from backend.core.ports.blackboard import BlackboardRepository
from backend.infrastructure.postgres.models import BlackboardEntryModel, BlackboardEventModel


class SqlAlchemyBlackboardRepository(BlackboardRepository):
    def __init__(self, session: Session) -> None:
        self._session = session

    async def append(
        self, entry: BlackboardEntry, *, expected_version: int
    ) -> BlackboardEntry:
        current = self._session.get(
            BlackboardEntryModel,
            (entry.entry_id, entry.workspace_id, entry.task_id),
        )
        actual = 0 if current is None else current.entry_version
        if actual != expected_version or entry.version != expected_version + 1:
            raise ProjectError(
                ErrorCode.FAILED_PRECONDITION,
                "Blackboard optimistic version conflict",
                {"entry_id": entry.entry_id, "expected": expected_version, "actual": actual},
            )
        event_type: Literal["created", "updated"] = (
            "created" if current is None else "updated"
        )
        model = current or BlackboardEntryModel(
            entry_id=entry.entry_id,
            workspace_id=entry.workspace_id,
            task_id=entry.task_id,
            kind=entry.kind.value,
            producer_role=entry.producer_role,
            entry_version=entry.version,
            confidence=entry.confidence,
            payload_json=entry.payload,
            source_json=entry.source.model_dump(mode="json"),
            created_at=entry.created_at,
            updated_at=entry.updated_at,
        )
        model.task_id = entry.task_id
        model.kind = entry.kind.value
        model.producer_role = entry.producer_role
        model.entry_version = entry.version
        model.confidence = entry.confidence
        model.payload_json = entry.payload
        model.source_json = entry.source.model_dump(mode="json")
        model.invalidated_at = entry.invalidated_at
        model.updated_at = entry.updated_at
        self._session.add(model)
        self._add_event(entry, event_type)
        self._session.flush()
        return entry

    async def list_active(self, workspace_id: str, task_id: str) -> list[BlackboardEntry]:
        rows = self._session.scalars(
            select(BlackboardEntryModel)
            .where(
                BlackboardEntryModel.workspace_id == workspace_id,
                BlackboardEntryModel.task_id == task_id,
                BlackboardEntryModel.invalidated_at.is_(None),
            )
            .order_by(BlackboardEntryModel.entry_id)
        )
        return [_entry_from_model(row) for row in rows]

    async def list_events(self, workspace_id: str, task_id: str) -> list[BlackboardEvent]:
        rows = self._session.scalars(
            select(BlackboardEventModel)
            .where(
                BlackboardEventModel.workspace_id == workspace_id,
                BlackboardEventModel.task_id == task_id,
            )
            .order_by(BlackboardEventModel.sequence)
        )
        return [
            BlackboardEvent(
                event_id=row.event_id,
                event_type=cast(
                    Literal["created", "updated", "invalidated"], row.event_type
                ),
                entry=BlackboardEntry.model_validate(row.entry_json),
                created_at=row.created_at,
            )
            for row in rows
        ]

    async def invalidate_source(
        self, workspace_id: str, source_type: str, source_id: str
    ) -> int:
        if source_type not in {"file", "message"}:
            raise ProjectError(ErrorCode.INVALID_ARGUMENT, "Unsupported Blackboard source type")
        rows = list(
            self._session.scalars(
                select(BlackboardEntryModel).where(
                    BlackboardEntryModel.workspace_id == workspace_id,
                    BlackboardEntryModel.invalidated_at.is_(None),
                )
            )
        )
        key = "file_id" if source_type == "file" else "message_id"
        affected_task_ids = {
            row.task_id for row in rows if row.source_json.get(key) == source_id
        }
        count = 0
        for row in rows:
            if row.task_id not in affected_task_ids:
                continue
            invalidated = _entry_from_model(row).invalidate()
            row.entry_version = invalidated.version
            row.invalidated_at = invalidated.invalidated_at
            row.updated_at = invalidated.updated_at
            self._add_event(invalidated, "invalidated")
            count += 1
        self._session.flush()
        return count

    def _add_event(
        self,
        entry: BlackboardEntry,
        event_type: Literal["created", "updated", "invalidated"],
    ) -> None:
        self._session.add(
            BlackboardEventModel(
                event_id=str(uuid4()),
                workspace_id=entry.workspace_id,
                task_id=entry.task_id,
                entry_id=entry.entry_id,
                event_type=event_type,
                entry_json=entry.model_dump(mode="json"),
            )
        )

    @staticmethod
    def rebuild(events: Sequence[BlackboardEvent]) -> dict[str, BlackboardEntry]:
        return BlackboardRepository.rebuild(events)


class ManagedSqlAlchemyBlackboardRepository(BlackboardRepository):
    """Short-lived transactional Blackboard adapter for long-running Workers."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sessions = session_factory

    async def append(
        self,
        entry: BlackboardEntry,
        *,
        expected_version: int,
    ) -> BlackboardEntry:
        with self._sessions() as session:
            saved = await SqlAlchemyBlackboardRepository(session).append(
                entry,
                expected_version=expected_version,
            )
            session.commit()
            return saved

    async def list_active(
        self,
        workspace_id: str,
        task_id: str,
    ) -> list[BlackboardEntry]:
        with self._sessions() as session:
            return await SqlAlchemyBlackboardRepository(session).list_active(
                workspace_id,
                task_id,
            )

    async def list_events(
        self,
        workspace_id: str,
        task_id: str,
    ) -> list[BlackboardEvent]:
        with self._sessions() as session:
            return await SqlAlchemyBlackboardRepository(session).list_events(
                workspace_id,
                task_id,
            )

    async def invalidate_source(
        self,
        workspace_id: str,
        source_type: str,
        source_id: str,
    ) -> int:
        with self._sessions() as session:
            count = await SqlAlchemyBlackboardRepository(
                session
            ).invalidate_source(workspace_id, source_type, source_id)
            session.commit()
            return count

    @staticmethod
    def rebuild(
        events: Sequence[BlackboardEvent],
    ) -> dict[str, BlackboardEntry]:
        return BlackboardRepository.rebuild(events)


def _entry_from_model(model: BlackboardEntryModel) -> BlackboardEntry:
    return BlackboardEntry.model_validate(
        {
            "entry_id": model.entry_id,
            "workspace_id": model.workspace_id,
            "task_id": model.task_id,
            "kind": model.kind,
            "producer_role": model.producer_role,
            "version": model.entry_version,
            "confidence": model.confidence,
            "payload": model.payload_json,
            "source": model.source_json,
            "invalidated_at": model.invalidated_at,
            "created_at": model.created_at,
            "updated_at": model.updated_at,
        }
    )
