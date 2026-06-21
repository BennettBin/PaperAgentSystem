import asyncio
import json
from dataclasses import dataclass
from datetime import datetime
from typing import AsyncIterator
from uuid import uuid4

from redis import Redis
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from infrastructure.postgres.models import TaskEventModel

TERMINAL_EVENTS = {"task_completed", "task_failed", "task_cancelled"}


@dataclass(frozen=True)
class StoredTaskEvent:
    event_id: str
    task_id: str
    sequence: int
    event_type: str
    title: str
    data: dict
    created_at: datetime

    def to_sse(self) -> str:
        payload = {
            "event_id": self.event_id,
            "task_id": self.task_id,
            "sequence": self.sequence,
            "type": self.event_type,
            "title": self.title,
            "data": self.data,
            "created_at": self.created_at.isoformat(),
        }
        return (
            f"id: {self.sequence}\n"
            f"event: {self.event_type}\n"
            f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        )

    @property
    def terminal(self) -> bool:
        return self.event_type in TERMINAL_EVENTS


class TaskEventStore:
    def __init__(
        self, session_factory: sessionmaker[Session], redis: Redis | None = None
    ) -> None:
        self.session_factory = session_factory
        self.redis = redis

    def append(
        self, task_id: str, event_type: str, title: str, data: dict | None = None
    ) -> StoredTaskEvent:
        with self.session_factory() as session:
            current = session.scalar(
                select(func.max(TaskEventModel.sequence)).where(
                    TaskEventModel.task_id == task_id
                )
            )
            model = TaskEventModel(
                event_id=uuid4().hex,
                task_id=task_id,
                sequence=(current or 0) + 1,
                event_type=event_type,
                title=title,
                data=data or {},
            )
            session.add(model)
            session.commit()
            session.refresh(model)
            event = _event(model)
        if self.redis is not None:
            self.redis.publish(f"task-events:{task_id}", str(event.sequence))
        return event

    def after(self, task_id: str, sequence: int) -> list[StoredTaskEvent]:
        with self.session_factory() as session:
            models = session.scalars(
                select(TaskEventModel)
                .where(
                    TaskEventModel.task_id == task_id,
                    TaskEventModel.sequence > sequence,
                )
                .order_by(TaskEventModel.sequence)
            )
            return [_event(model) for model in models]


class TaskEventStream:
    def __init__(self, store: TaskEventStore, poll_interval: float = 0.05) -> None:
        self.store = store
        self.poll_interval = poll_interval

    async def events(
        self, task_id: str, last_sequence: int = 0
    ) -> AsyncIterator[StoredTaskEvent]:
        cursor = last_sequence
        while True:
            pending = self.store.after(task_id, cursor)
            if not pending:
                await asyncio.sleep(self.poll_interval)
                continue
            for event in pending:
                if event.sequence <= cursor:
                    continue
                cursor = event.sequence
                yield event
                if event.terminal:
                    return

    async def sse(self, task_id: str, last_sequence: int = 0) -> AsyncIterator[str]:
        async for event in self.events(task_id, last_sequence):
            yield event.to_sse()


def _event(model: TaskEventModel) -> StoredTaskEvent:
    return StoredTaskEvent(
        event_id=model.event_id,
        task_id=model.task_id,
        sequence=model.sequence,
        event_type=model.event_type,
        title=model.title,
        data=model.data,
        created_at=model.created_at,
    )
