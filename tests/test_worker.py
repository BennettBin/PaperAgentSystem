import pytest

from apps.worker.fake_queue import FakeTaskQueue
from apps.worker.handler_registry import HandlerRegistry
from apps.worker.main import create_worker
from apps.worker.tasks import (
    CancellationToken,
    DocumentParseTask,
    MainAgentTask,
    MemorySummaryTask,
    RetryPolicy,
    SubAgentTask,
    TaskStatus,
    TaskType,
)
from core.domain.ids import TaskId, WorkspaceId


@pytest.mark.asyncio
async def test_main_agent_task_creation():
    task = MainAgentTask(
        task_id=TaskId.generate(),
        workspace_id=WorkspaceId.generate(),
        payload={"input": "test"},
        idempotency_key="key1",
    )
    assert task.task_type == TaskType.MAIN_AGENT
    assert task.retries == 0


@pytest.mark.asyncio
async def test_sub_agent_task_creation():
    parent_id = TaskId.generate()
    task = SubAgentTask(
        task_id=TaskId.generate(),
        workspace_id=WorkspaceId.generate(),
        payload={"input": "test"},
        idempotency_key="key2",
        parent_task_id=parent_id,
    )
    assert task.task_type == TaskType.SUB_AGENT
    assert task.parent_task_id == parent_id


@pytest.mark.asyncio
async def test_fake_queue_enqueue():
    queue = FakeTaskQueue()
    task = MainAgentTask(
        task_id=TaskId.generate(),
        workspace_id=WorkspaceId.generate(),
        payload={"input": "test"},
        idempotency_key="key1",
    )
    task_id = await queue.enqueue(task)
    assert task_id == "key1"
    assert await queue.get_status(task_id) == TaskStatus.PENDING


@pytest.mark.asyncio
async def test_fake_queue_idempotency():
    queue = FakeTaskQueue()
    task = MainAgentTask(
        task_id=TaskId.generate(),
        workspace_id=WorkspaceId.generate(),
        payload={"input": "test"},
        idempotency_key="key1",
    )
    await queue.enqueue(task, idempotency_key="unique_key")
    await queue.enqueue(task, idempotency_key="unique_key")
    # 第二次应该返回相同的 key（去重）
    assert len(queue.results) == 1


@pytest.mark.asyncio
async def test_fake_queue_execute():
    queue = FakeTaskQueue()

    def handler(task):
        return {"result": "success", "task_id": str(task.task_id)}

    queue.register_handler(TaskType.MAIN_AGENT.value, handler)

    task = MainAgentTask(
        task_id=TaskId.generate(),
        workspace_id=WorkspaceId.generate(),
        payload={"input": "test"},
        idempotency_key="key1",
    )
    task_id = await queue.enqueue(task)
    await queue.execute(task_id)

    assert await queue.get_status(task_id) == TaskStatus.COMPLETED
    result = await queue.get_result(task_id)
    assert result["result"] == "success"


@pytest.mark.asyncio
async def test_fake_queue_cancel():
    queue = FakeTaskQueue()
    task = MainAgentTask(
        task_id=TaskId.generate(),
        workspace_id=WorkspaceId.generate(),
        payload={"input": "test"},
        idempotency_key="key1",
    )
    task_id = await queue.enqueue(task)
    result = await queue.cancel(task_id)
    assert result is True
    assert await queue.get_status(task_id) == TaskStatus.CANCELLED


@pytest.mark.asyncio
async def test_fake_queue_failure():
    queue = FakeTaskQueue()
    queue.should_fail = True

    task = MainAgentTask(
        task_id=TaskId.generate(),
        workspace_id=WorkspaceId.generate(),
        payload={"input": "test"},
        idempotency_key="key1",
    )
    task_id = await queue.enqueue(task)
    await queue.execute(task_id)

    assert await queue.get_status(task_id) == TaskStatus.FAILED


@pytest.mark.asyncio
async def test_handler_registry():
    registry = HandlerRegistry()

    def handler(task):
        return {"processed": True}

    registry.register(TaskType.MAIN_AGENT, handler)
    assert registry.get(TaskType.MAIN_AGENT) is not None

    task = MainAgentTask(
        task_id=TaskId.generate(),
        workspace_id=WorkspaceId.generate(),
        payload={},
        idempotency_key="key1",
    )
    result = registry.handle(task)
    assert result["processed"] is True


@pytest.mark.asyncio
async def test_create_worker():
    queue, registry = create_worker()
    assert queue is not None
    assert registry is not None
    handlers = registry.list_handlers()
    assert TaskType.MAIN_AGENT.value in handlers
    assert TaskType.SUB_AGENT.value in handlers
    assert TaskType.DOCUMENT_PARSE.value in handlers
    assert TaskType.MEMORY_SUMMARY.value in handlers


@pytest.mark.asyncio
async def test_multiple_task_types():
    queue, registry = create_worker()

    tasks = [
        MainAgentTask(
            task_id=TaskId.generate(),
            workspace_id=WorkspaceId.generate(),
            payload={"input": "test1"},
            idempotency_key="key1",
        ),
        DocumentParseTask(
            task_id=TaskId.generate(),
            workspace_id=WorkspaceId.generate(),
            payload={"input": "test2"},
            idempotency_key="key2",
        ),
        MemorySummaryTask(
            task_id=TaskId.generate(),
            workspace_id=WorkspaceId.generate(),
            payload={"input": "test3"},
            idempotency_key="key3",
        ),
    ]

    for task in tasks:
        task_id = await queue.enqueue(task)
        await queue.execute(task_id)
        assert await queue.get_status(task_id) == TaskStatus.COMPLETED


@pytest.mark.asyncio
async def test_queue_accepts_port_shape_and_async_handler():
    queue = FakeTaskQueue()

    async def handler(task):
        return {"echo": task.payload["input"]}

    queue.register_handler("main_agent", handler)
    task_id = await queue.enqueue(
        task_type="main_agent",
        payload={"input": "hello"},
        idempotency_key="port-key",
    )
    await queue.execute(task_id)

    assert await queue.get_result(task_id) == {"echo": "hello"}


@pytest.mark.asyncio
async def test_cancelled_task_is_not_executed():
    queue = FakeTaskQueue()
    called = False

    def handler(task):
        nonlocal called
        called = True

    queue.register_handler("main_agent", handler)
    task_id = await queue.enqueue("main_agent", {}, "cancel-key")
    await queue.cancel(task_id)
    await queue.execute(task_id)

    assert called is False
    assert await queue.get_status(task_id) == TaskStatus.CANCELLED


def test_cancellation_token_and_retry_policy():
    token = CancellationToken("token-1")
    assert token.cancelled is False
    token.cancel()
    assert token.cancelled is True

    policy = RetryPolicy(max_retries=2)
    assert policy.can_retry(1)
    assert not policy.can_retry(2)
