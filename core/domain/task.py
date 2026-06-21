"""
任务、计划和步骤实体
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Optional

from core.domain.enums import StepStatus, TaskStatus
from core.domain.ids import (
    ConversationId,
    PlanId,
    StepId,
    TaskId,
    ToolCallId,
    TraceId,
    UserId,
    WorkspaceId,
)


@dataclass
class Task:
    """任务实体

    代表用户对话中的一个任务（请求）。
    """

    id: TaskId
    workspace_id: WorkspaceId
    user_id: UserId
    conversation_id: ConversationId
    status: TaskStatus
    input_text: str
    result: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    trace_id: Optional[TraceId] = None
    metadata: dict = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        workspace_id: WorkspaceId,
        user_id: UserId,
        conversation_id: ConversationId,
        input_text: str,
    ) -> "Task":
        """创建新任务"""
        now = datetime.now(UTC)
        return cls(
            id=TaskId.generate(),
            workspace_id=workspace_id,
            user_id=user_id,
            conversation_id=conversation_id,
            status=TaskStatus.RECEIVED,
            input_text=input_text,
            created_at=now,
            updated_at=now,
        )

    def transition_to(self, new_status: TaskStatus) -> None:
        """状态转换

        验证允许的状态转换。
        """
        # 定义允许的转换
        allowed_transitions = {
            TaskStatus.RECEIVED: [TaskStatus.UNDERSTANDING, TaskStatus.CANCELLED],
            TaskStatus.UNDERSTANDING: [
                TaskStatus.REQUIREMENT_CHECK,
                TaskStatus.CANCELLED,
            ],
            TaskStatus.REQUIREMENT_CHECK: [
                TaskStatus.CLARIFYING,
                TaskStatus.SKILL_SELECTED,
                TaskStatus.CANCELLED,
            ],
            TaskStatus.CLARIFYING: [TaskStatus.WAITING_USER, TaskStatus.CANCELLED],
            TaskStatus.WAITING_USER: [TaskStatus.REQUIREMENT_CHECK, TaskStatus.CANCELLED],
            TaskStatus.SKILL_SELECTED: [TaskStatus.PLANNED, TaskStatus.CANCELLED],
            TaskStatus.PLANNED: [TaskStatus.EXECUTING, TaskStatus.REPLANNING, TaskStatus.CANCELLED],
            TaskStatus.EXECUTING: [
                TaskStatus.VERIFYING,
                TaskStatus.FAILED,
                TaskStatus.CANCELLED,
            ],
            TaskStatus.VERIFYING: [TaskStatus.COMPLETED, TaskStatus.REPLANNING, TaskStatus.FAILED],
            TaskStatus.REPLANNING: [TaskStatus.PLANNED, TaskStatus.FAILED],
        }

        if new_status not in allowed_transitions.get(self.status, []):
            raise ValueError(f"Invalid transition from {self.status} to {new_status}")

        self.status = new_status
        self.updated_at = datetime.now(UTC)


@dataclass
class Plan:
    """计划实体

    任务的执行计划。
    """

    id: PlanId
    task_id: TaskId
    steps: list["Step"] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict = field(default_factory=dict)

    @classmethod
    def create(cls, task_id: TaskId) -> "Plan":
        """创建新计划"""
        return cls(
            id=PlanId.generate(),
            task_id=task_id,
        )

    def add_step(self, step: "Step") -> None:
        """添加步骤"""
        if step not in self.steps:
            self.steps.append(step)


@dataclass
class Step:
    """步骤实体

    计划中的单个步骤。
    """

    id: StepId
    plan_id: PlanId
    index: int
    title: str
    description: Optional[str]
    status: StepStatus
    dependencies: list[StepId] = field(default_factory=list)
    tool_calls: list["ToolCall"] = field(default_factory=list)
    result: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        plan_id: PlanId,
        index: int,
        title: str,
        description: Optional[str] = None,
        dependencies: Optional[list[StepId]] = None,
    ) -> "Step":
        """创建新步骤"""
        return cls(
            id=StepId.generate(),
            plan_id=plan_id,
            index=index,
            title=title,
            description=description,
            status=StepStatus.PENDING,
            dependencies=dependencies or [],
        )

    def transition_to(self, new_status: StepStatus) -> None:
        """状态转换"""
        allowed = {
            StepStatus.PENDING: [StepStatus.RUNNING, StepStatus.SKIPPED],
            StepStatus.RUNNING: [StepStatus.COMPLETED, StepStatus.FAILED],
            StepStatus.COMPLETED: [],
            StepStatus.FAILED: [],
            StepStatus.SKIPPED: [],
        }

        if new_status not in allowed.get(self.status, []):
            raise ValueError(f"Invalid step transition from {self.status} to {new_status}")

        self.status = new_status
        self.updated_at = datetime.now(UTC)


@dataclass
class ToolCall:
    """Tool 调用实体"""

    id: ToolCallId
    step_id: StepId
    tool_name: str
    parameters: dict
    result: Optional[dict] = None
    error_message: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: Optional[datetime] = None
    metadata: dict = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        step_id: StepId,
        tool_name: str,
        parameters: dict,
    ) -> "ToolCall":
        """创建新 Tool 调用"""
        return cls(
            id=ToolCallId.generate(),
            step_id=step_id,
            tool_name=tool_name,
            parameters=parameters,
        )
