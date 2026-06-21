"""
Fake 任务队列实现

用于开发和测试，将任务存储在内存中。
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from apps.worker.tasks import BaseTask, CancellationToken, TaskStatus, TaskType
from core.ports.storage import TaskQueue


@dataclass
class TaskResult:
    """任务执行结果"""

    status: TaskStatus
    result: Optional[Any] = None
    error: Optional[str] = None


@dataclass
class FakeTaskQueue(TaskQueue):
    """
    Fake 任务队列，用于测试和开发

    不需要 Redis/Celery，所有任务存储在内存中。
    可配置成功/失败/超时场景。
    """

    tasks: dict[str, BaseTask | QueueTask] = field(default_factory=dict)
    results: dict[str, TaskResult] = field(default_factory=dict)
    handlers: dict[str, Callable] = field(default_factory=dict)
    should_fail: bool = False
    should_timeout: bool = False
    cancellation_tokens: dict[str, CancellationToken] = field(default_factory=dict)

    async def enqueue(
        self,
        task_type: str | BaseTask,
        payload: Optional[dict] = None,
        idempotency_key: Optional[str] = None,
        priority: int = 0,
    ) -> str:
        """入队任务"""
        if isinstance(task_type, BaseTask):
            queued_task: BaseTask | QueueTask = task_type
            key = idempotency_key or queued_task.idempotency_key
        else:
            key = idempotency_key or f"{task_type}:{len(self.tasks) + 1}"
            queued_task = QueueTask(task_type=task_type, payload=payload or {}, idempotency_key=key)
        # 去重检查
        if key in self.results:
            return key
        self.tasks[key] = queued_task
        self.results[key] = TaskResult(status=TaskStatus.PENDING)
        self.cancellation_tokens[key] = CancellationToken(token_id=key)
        return key

    async def get_status(self, task_id: str) -> TaskStatus:
        """获取任务状态"""
        return self.results.get(task_id, TaskResult(status=TaskStatus.FAILED)).status

    async def get_result(self, task_id: str) -> Optional[Any]:
        """获取任务结果"""
        result = self.results.get(task_id)
        return result.result if result else None

    async def cancel(self, task_id: str) -> bool:
        """取消任务"""
        if task_id in self.results:
            self.results[task_id].status = TaskStatus.CANCELLED
            self.cancellation_tokens[task_id].cancel()
            return True
        return False

    async def execute(self, task_id: str) -> None:
        """执行任务（测试用）"""
        if task_id not in self.tasks:
            self.results[task_id] = TaskResult(status=TaskStatus.FAILED, error="Task not found")
            return

        task = self.tasks[task_id]
        token = self.cancellation_tokens[task_id]
        if token.cancelled:
            return
        self.results[task_id].status = TaskStatus.RUNNING

        if self.should_fail:
            self.results[task_id] = TaskResult(status=TaskStatus.FAILED, error="Simulated failure")
            return

        if self.should_timeout:
            self.results[task_id] = TaskResult(status=TaskStatus.FAILED, error="Task timeout")
            return

        # 查找对应的处理器
        task_type = task.task_type.value if isinstance(task.task_type, TaskType) else task.task_type
        handler = self.handlers.get(task_type)
        if handler:
            try:
                result = handler(task)
                if inspect.isawaitable(result):
                    result = await result
                token.raise_if_cancelled()
                self.results[task_id] = TaskResult(status=TaskStatus.COMPLETED, result=result)
            except Exception as e:
                self.results[task_id] = TaskResult(status=TaskStatus.FAILED, error=str(e))
        else:
            self.results[task_id] = TaskResult(
                status=TaskStatus.FAILED, error=f"No handler for {task.task_type}"
            )

    def register_handler(self, task_type: str, handler: Callable) -> None:
        """注册任务处理器"""
        self.handlers[task_type] = handler


@dataclass(frozen=True)
class QueueTask:
    task_type: str
    payload: dict
    idempotency_key: str
