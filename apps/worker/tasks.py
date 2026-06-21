"""
任务类型定义

所有后台任务必须继承 BaseTask。
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Optional

from core.domain.ids import TaskId, WorkspaceId


class TaskType(str, Enum):
    """任务类型"""

    MAIN_AGENT = "main_agent"
    SUB_AGENT = "sub_agent"
    DOCUMENT_PARSE = "document_parse"
    MEMORY_SUMMARY = "memory_summary"


class TaskStatus(str, Enum):
    """任务状态"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class CancellationToken:
    token_id: str
    cancelled: bool = False

    def cancel(self) -> None:
        self.cancelled = True

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise TaskCancelledError(self.token_id)


class TaskCancelledError(RuntimeError):
    pass


@dataclass(frozen=True)
class RetryPolicy:
    max_retries: int = 3
    delay_seconds: int = 5

    def can_retry(self, attempts: int) -> bool:
        return attempts < self.max_retries


@dataclass(frozen=True)
class BaseTask:
    """所有任务的基类"""

    task_id: TaskId
    workspace_id: WorkspaceId
    task_type: TaskType
    payload: dict[str, Any]
    idempotency_key: str
    retries: int = 0
    max_retries: int = 3
    retry_delay_seconds: int = 5
    timeout_seconds: int = 300
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    cancel_token: Optional[str] = None

    def with_retry(self) -> "BaseTask":
        """增加重试计数，返回新实例"""
        if self.retries >= self.max_retries:
            raise ValueError(f"Max retries ({self.max_retries}) exceeded")
        # 创建一个新的冻结实例（通过 dict 转换）
        new_data = self.__dict__.copy()
        new_data["retries"] = self.retries + 1
        return BaseTask(**new_data)


class MainAgentTask(BaseTask):
    """主 Agent 任务"""

    def __init__(
        self,
        task_id: TaskId,
        workspace_id: WorkspaceId,
        payload: dict[str, Any],
        idempotency_key: str,
        retries: int = 0,
        max_retries: int = 3,
        retry_delay_seconds: int = 5,
        timeout_seconds: int = 300,
        created_at: Optional[datetime] = None,
        cancel_token: Optional[str] = None,
    ):
        if created_at is None:
            created_at = datetime.now(UTC)
        object.__setattr__(self, "task_id", task_id)
        object.__setattr__(self, "workspace_id", workspace_id)
        object.__setattr__(self, "task_type", TaskType.MAIN_AGENT)
        object.__setattr__(self, "payload", payload)
        object.__setattr__(self, "idempotency_key", idempotency_key)
        object.__setattr__(self, "retries", retries)
        object.__setattr__(self, "max_retries", max_retries)
        object.__setattr__(self, "retry_delay_seconds", retry_delay_seconds)
        object.__setattr__(self, "timeout_seconds", timeout_seconds)
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "cancel_token", cancel_token)


class SubAgentTask(BaseTask):
    """子 Agent 任务"""

    def __init__(
        self,
        task_id: TaskId,
        workspace_id: WorkspaceId,
        payload: dict[str, Any],
        idempotency_key: str,
        parent_task_id: Optional[TaskId] = None,
        retries: int = 0,
        max_retries: int = 3,
        retry_delay_seconds: int = 5,
        timeout_seconds: int = 300,
        created_at: Optional[datetime] = None,
        cancel_token: Optional[str] = None,
    ):
        if created_at is None:
            created_at = datetime.now(UTC)
        object.__setattr__(self, "task_id", task_id)
        object.__setattr__(self, "workspace_id", workspace_id)
        object.__setattr__(self, "task_type", TaskType.SUB_AGENT)
        object.__setattr__(self, "payload", payload)
        object.__setattr__(self, "idempotency_key", idempotency_key)
        object.__setattr__(self, "retries", retries)
        object.__setattr__(self, "max_retries", max_retries)
        object.__setattr__(self, "retry_delay_seconds", retry_delay_seconds)
        object.__setattr__(self, "timeout_seconds", timeout_seconds)
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "cancel_token", cancel_token)
        object.__setattr__(self, "parent_task_id", parent_task_id)

    @property
    def parent_task_id(self) -> Optional[TaskId]:
        """获取父任务 ID"""
        value: Optional[TaskId] = object.__getattribute__(self, "_parent_task_id")
        return value

    @parent_task_id.setter
    def parent_task_id(self, value: Optional[TaskId]) -> None:
        object.__setattr__(self, "_parent_task_id", value)


class DocumentParseTask(BaseTask):
    """文档解析任务"""

    def __init__(
        self,
        task_id: TaskId,
        workspace_id: WorkspaceId,
        payload: dict[str, Any],
        idempotency_key: str,
        retries: int = 0,
        max_retries: int = 3,
        retry_delay_seconds: int = 5,
        timeout_seconds: int = 300,
        created_at: Optional[datetime] = None,
        cancel_token: Optional[str] = None,
    ):
        if created_at is None:
            created_at = datetime.now(UTC)
        object.__setattr__(self, "task_id", task_id)
        object.__setattr__(self, "workspace_id", workspace_id)
        object.__setattr__(self, "task_type", TaskType.DOCUMENT_PARSE)
        object.__setattr__(self, "payload", payload)
        object.__setattr__(self, "idempotency_key", idempotency_key)
        object.__setattr__(self, "retries", retries)
        object.__setattr__(self, "max_retries", max_retries)
        object.__setattr__(self, "retry_delay_seconds", retry_delay_seconds)
        object.__setattr__(self, "timeout_seconds", timeout_seconds)
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "cancel_token", cancel_token)


class MemorySummaryTask(BaseTask):
    """记忆摘要任务"""

    def __init__(
        self,
        task_id: TaskId,
        workspace_id: WorkspaceId,
        payload: dict[str, Any],
        idempotency_key: str,
        retries: int = 0,
        max_retries: int = 3,
        retry_delay_seconds: int = 5,
        timeout_seconds: int = 300,
        created_at: Optional[datetime] = None,
        cancel_token: Optional[str] = None,
    ):
        if created_at is None:
            created_at = datetime.now(UTC)
        object.__setattr__(self, "task_id", task_id)
        object.__setattr__(self, "workspace_id", workspace_id)
        object.__setattr__(self, "task_type", TaskType.MEMORY_SUMMARY)
        object.__setattr__(self, "payload", payload)
        object.__setattr__(self, "idempotency_key", idempotency_key)
        object.__setattr__(self, "retries", retries)
        object.__setattr__(self, "max_retries", max_retries)
        object.__setattr__(self, "retry_delay_seconds", retry_delay_seconds)
        object.__setattr__(self, "timeout_seconds", timeout_seconds)
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "cancel_token", cancel_token)
