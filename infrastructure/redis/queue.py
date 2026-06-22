import json
import time
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, Callable, Iterator, Optional
from uuid import uuid4

from redis import Redis
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from core.ports.storage import EventPublisher, TaskQueue
from infrastructure.postgres.models import QueueJobModel

QUEUE_BY_TASK = {
    "main_agent": "main_agent",
    "sub_agent": "sub_agent",
    "document_parse": "document_parse",
    "memory_summary": "memory_summary",
}


class RedisTaskQueue(TaskQueue):
    def __init__(self, redis: Redis, session_factory: sessionmaker[Session]) -> None:
        self.redis = redis
        self.session_factory = session_factory
        self.handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {}

    async def enqueue(
        self,
        task_type: str,
        payload: dict,
        idempotency_key: str,
        priority: int = 0,
    ) -> str:
        queue_name = QUEUE_BY_TASK.get(task_type)
        if queue_name is None:
            raise ValueError(f"Unsupported task type: {task_type}")
        with self.session_factory() as session:
            existing = session.scalar(
                select(QueueJobModel).where(QueueJobModel.idempotency_key == idempotency_key)
            )
            if existing is not None:
                return existing.id
            task_id = uuid4().hex
            session.add(
                QueueJobModel(
                    id=task_id,
                    task_type=task_type,
                    queue_name=queue_name,
                    payload=payload,
                    idempotency_key=idempotency_key,
                    status="queued",
                    priority=priority,
                    max_retries=3,
                )
            )
            session.commit()
        self.redis.lpush(f"queue:{queue_name}", task_id)
        return task_id

    async def get_status(self, task_id: str) -> str:
        with self.session_factory() as session:
            job = session.get(QueueJobModel, task_id)
            return "missing" if job is None else job.status

    async def get_result(self, task_id: str) -> Optional[dict]:
        with self.session_factory() as session:
            job = session.get(QueueJobModel, task_id)
            return None if job is None else job.result

    async def cancel(self, task_id: str) -> bool:
        with self.session_factory() as session:
            job = session.get(QueueJobModel, task_id)
            if job is None or job.status in {"completed", "failed", "cancelled"}:
                return False
            job.status = "cancelled"
            session.commit()
        self.redis.set(f"cancel:{task_id}", "1", ex=3600)
        return True

    def is_cancelled(self, task_id: str) -> bool:
        if self.redis.exists(f"cancel:{task_id}"):
            return True
        with self.session_factory() as session:
            job = session.get(QueueJobModel, task_id)
            return job is not None and job.status == "cancelled"

    def register_handler(
        self, task_type: str, handler: Callable[[dict[str, Any]], dict[str, Any]]
    ) -> None:
        self.handlers[task_type] = handler

    def execute_next(self, queue_name: str, timeout: int = 1) -> str | None:
        item = self.redis.brpop(f"queue:{queue_name}", timeout=timeout)
        if item is None:
            return None
        raw_task_id = item[1]
        task_id = raw_task_id.decode() if isinstance(raw_task_id, bytes) else raw_task_id
        with self.session_factory() as session:
            job = session.get(QueueJobModel, task_id)
            if job is None or job.status == "cancelled":
                return task_id
            job.status = "running"
            job.attempts += 1
            job.heartbeat_at = datetime.now(UTC)
            session.commit()
            handler = self.handlers.get(job.task_type)
            try:
                if handler is None:
                    raise RuntimeError(f"No handler for {job.task_type}")
                result = handler({**job.payload, "_task_id": task_id})
                if self.is_cancelled(task_id):
                    job.status = "cancelled"
                else:
                    job.status, job.result = "completed", result
                session.commit()
            except Exception as exc:
                job.error = str(exc)
                if job.attempts <= job.max_retries:
                    job.status = "queued"
                    session.commit()
                    delay = min(2 ** (job.attempts - 1), 60)
                    time.sleep(delay / 100)
                    self.redis.lpush(f"queue:{job.queue_name}", task_id)
                else:
                    job.status = "failed"
                    session.commit()
                    self.redis.lpush("queue:dead_letter", task_id)
        return task_id

    def recover_stale(self, older_than_seconds: int = 30) -> int:
        threshold = datetime.now(UTC) - timedelta(seconds=older_than_seconds)
        recovered = 0
        with self.session_factory() as session:
            jobs = session.scalars(
                select(QueueJobModel).where(
                    QueueJobModel.status == "running",
                    QueueJobModel.heartbeat_at < threshold,
                )
            )
            for job in jobs:
                job.status = "queued"
                self.redis.lpush(f"queue:{job.queue_name}", job.id)
                recovered += 1
            session.commit()
        return recovered

    @contextmanager
    def lock(self, name: str, timeout_seconds: int = 10) -> Iterator[bool]:
        lock = self.redis.lock(f"lock:{name}", timeout=timeout_seconds)
        acquired = lock.acquire(blocking=False)
        try:
            yield acquired
        finally:
            if acquired:
                lock.release()


class RedisEventPublisher(EventPublisher):
    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    async def publish(self, event_type: str, data: dict, channel: Optional[str] = None) -> None:
        selected = channel or "global"
        event = json.dumps({"type": event_type, "data": data})
        pipe = self.redis.pipeline()
        pipe.rpush(f"events:{selected}", event)
        pipe.publish(f"notify:{selected}", event)
        pipe.execute()

    async def subscribe(self, channel: str) -> list[dict]:
        return [json.loads(item) for item in self.redis.lrange(f"events:{channel}", 0, -1)]
