"""
任务处理器注册表

管理所有任务类型的处理器。
"""

from typing import Callable, Dict, Optional
from apps.worker.tasks import BaseTask, TaskType


class HandlerRegistry:
    """任务处理器注册表"""

    def __init__(self):
        self._handlers: Dict[TaskType, Callable] = {}

    def register(self, task_type: TaskType, handler: Callable) -> None:
        """注册处理器"""
        if task_type in self._handlers:
            raise ValueError(f"Handler for {task_type} already registered")
        self._handlers[task_type] = handler

    def get(self, task_type: TaskType) -> Optional[Callable]:
        """获取处理器"""
        return self._handlers.get(task_type)

    def handle(self, task: BaseTask):
        """处理任务"""
        handler = self.get(task.task_type)
        if not handler:
            raise ValueError(f"No handler for {task.task_type}")
        return handler(task)

    def list_handlers(self) -> Dict[str, str]:
        """列出所有已注册的处理器"""
        return {task_type.value: handler.__name__ for task_type, handler in self._handlers.items()}
