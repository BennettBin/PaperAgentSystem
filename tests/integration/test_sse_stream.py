import pytest
from fastapi.testclient import TestClient
from redis import Redis
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from testcontainers.redis import RedisContainer

from apps.api.config import ApiSettings
from apps.api.dependencies import build_fake_container
from apps.api.main import create_app
from infrastructure.postgres.models import Base
from infrastructure.sse.service import TaskEventStore, TaskEventStream

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def redis_client():
    with RedisContainer("redis:7-alpine") as container:
        yield Redis(
            host=container.get_container_host_ip(),
            port=int(container.get_exposed_port(6379)),
        )


@pytest.fixture
def event_system(redis_client, tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'events.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    store = TaskEventStore(factory, redis_client)
    return store, TaskEventStream(store, poll_interval=0.001)


@pytest.mark.asyncio
async def test_disconnect_reconnect_deduplicate_and_terminal_close(event_system):
    store, stream = event_system
    first = store.append("task-1", "task_started", "Started")
    second = store.append("task-1", "step_completed", "Step")
    terminal = store.append("task-1", "task_completed", "Done")

    replay = [event async for event in stream.events("task-1", first.sequence)]
    assert [event.sequence for event in replay] == [second.sequence, terminal.sequence]
    assert len({event.sequence for event in replay}) == 2


@pytest.mark.asyncio
async def test_redis_restart_does_not_lose_database_events(event_system, redis_client):
    store, stream = event_system
    store.append("task-2", "task_started", "Started")
    terminal = store.append("task-2", "task_failed", "Failed")
    redis_client.flushall()
    replay = [event async for event in stream.events("task-2", 0)]
    assert replay[-1].sequence == terminal.sequence
    assert replay[-1].terminal


def test_sse_route_last_event_id_and_page_refresh(event_system):
    store, stream = event_system
    first = store.append("task-route", "task_started", "Started")
    store.append("task-route", "task_completed", "Done")
    container = build_fake_container()
    object.__setattr__(container, "event_stream", stream)
    app = create_app(ApiSettings(_env_file=None), container)
    response = TestClient(app).get(
        "/api/v1/tasks/task-route/events",
        headers={"Last-Event-ID": str(first.sequence)},
    )
    assert response.status_code == 200
    assert response.text.count("event: task_completed") == 1
    assert "event: task_started" not in response.text
