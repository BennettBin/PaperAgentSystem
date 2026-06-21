import time
from datetime import UTC, datetime, timedelta

import pytest
from redis import Redis
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from testcontainers.redis import RedisContainer

from infrastructure.postgres.models import Base, QueueJobModel
from infrastructure.redis.celery_app import create_celery_app
from infrastructure.redis.queue import RedisEventPublisher, RedisTaskQueue

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def redis_client():
    with RedisContainer("redis:7-alpine") as container:
        client = Redis(
            host=container.get_container_host_ip(),
            port=int(container.get_exposed_port(6379)),
            decode_responses=False,
        )
        yield client


@pytest.fixture
def queue(redis_client, tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'queue.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    return RedisTaskQueue(redis_client, factory), factory


@pytest.mark.asyncio
async def test_enqueue_execute_duplicate_and_database_truth(queue):
    task_queue, factory = queue
    task_queue.register_handler("main_agent", lambda payload: {"echo": payload["value"]})
    first = await task_queue.enqueue("main_agent", {"value": 7}, "same")
    second = await task_queue.enqueue("main_agent", {"value": 9}, "same")
    assert first == second
    task_queue.execute_next("main_agent")
    assert await task_queue.get_status(first) == "completed"
    assert await task_queue.get_result(first) == {"echo": 7}
    task_queue.redis.flushall()
    assert await task_queue.get_status(first) == "completed"
    with factory() as session:
        assert session.get(QueueJobModel, first) is not None


@pytest.mark.asyncio
async def test_retry_dead_letter_cancel_and_lock(queue):
    task_queue, factory = queue

    def failing(payload):
        raise RuntimeError("boom")

    task_queue.register_handler("document_parse", failing)
    task_id = await task_queue.enqueue("document_parse", {}, "failure")
    for _ in range(4):
        task_queue.execute_next("document_parse")
    assert await task_queue.get_status(task_id) == "failed"
    assert task_queue.redis.llen("queue:dead_letter") == 1

    cancelled = await task_queue.enqueue("memory_summary", {}, "cancel")
    started = time.monotonic()
    assert await task_queue.cancel(cancelled)
    assert task_queue.is_cancelled(cancelled)
    assert time.monotonic() - started < 2

    with task_queue.lock("task", 2) as acquired:
        assert acquired
        with task_queue.lock("task", 2) as duplicate:
            assert not duplicate

    crashed = await task_queue.enqueue("sub_agent", {}, "crashed")
    with factory() as session:
        job = session.get(QueueJobModel, crashed)
        assert job is not None
        job.status = "running"
        job.heartbeat_at = datetime.now(UTC) - timedelta(minutes=5)
        session.commit()
    assert task_queue.recover_stale(30) == 1
    assert await task_queue.get_status(crashed) == "queued"


@pytest.mark.asyncio
async def test_event_publisher_and_celery_routes(redis_client):
    publisher = RedisEventPublisher(redis_client)
    await publisher.publish("task_started", {"task_id": "1"}, channel="task:1")
    assert await publisher.subscribe("task:1") == [
        {"type": "task_started", "data": {"task_id": "1"}}
    ]
    app = create_celery_app("redis://localhost/0", "redis://localhost/0")
    assert {queue.name for queue in app.conf.task_queues} >= {
        "main_agent",
        "sub_agent",
        "document_parse",
        "memory_summary",
        "dead_letter",
    }
