"""
SSE 事件定义

前端通过 SSE 接收任务执行过程中的事件。
"""

from dataclasses import dataclass, asdict
from typing import Any, Optional
from datetime import datetime
from enum import Enum
from uuid import uuid4
import json


# ==================== 事件类型 ====================
class TaskEventType(str, Enum):
    """任务事件类型"""

    TASK_QUEUED = "task_queued"
    TASK_STARTED = "task_started"
    REQUIREMENT_CLARIFICATION_REQUESTED = "requirement_clarification_requested"
    REQUIREMENT_CLARIFICATION_RECEIVED = "requirement_clarification_received"
    SKILL_SELECTED = "skill_selected"
    PLAN_CREATED = "plan_created"
    STEP_STARTED = "step_started"
    STEP_COMPLETED = "step_completed"
    STEP_FAILED = "step_failed"
    TOOL_STARTED = "tool_started"
    TOOL_COMPLETED = "tool_completed"
    TOOL_FAILED = "tool_failed"
    SUBAGENT_STARTED = "subagent_started"
    SUBAGENT_COMPLETED = "subagent_completed"
    SUBAGENT_FAILED = "subagent_failed"
    VERIFICATION_FAILED = "verification_failed"
    ARTIFACT_CREATED = "artifact_created"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    TASK_CANCELLED = "task_cancelled"


# ==================== 基类事件 ====================
@dataclass
class BaseTaskEvent:
    """基类事件"""

    event_id: str
    task_id: str
    event_type: str
    sequence: int
    timestamp: datetime
    trace_id: Optional[str] = None
    parent_event_id: Optional[str] = None
    data: dict = None

    def __post_init__(self):
        if self.data is None:
            self.data = {}

    def to_sse_format(self) -> str:
        """转换为 SSE 格式"""
        payload = {
            "event_id": self.event_id,
            "task_id": self.task_id,
            "event_type": self.event_type,
            "sequence": self.sequence,
            "timestamp": self.timestamp.isoformat(),
            "trace_id": self.trace_id,
            "data": self.data,
        }
        return f"data: {json.dumps(payload)}\n\n"

    @classmethod
    def create(
        cls,
        task_id: str,
        event_type: TaskEventType,
        sequence: int,
        data: Optional[dict] = None,
        trace_id: Optional[str] = None,
        parent_event_id: Optional[str] = None,
    ) -> "BaseTaskEvent":
        """创建事件"""
        return cls(
            event_id=str(uuid4()),
            task_id=task_id,
            event_type=event_type.value,
            sequence=sequence,
            timestamp=datetime.utcnow(),
            trace_id=trace_id,
            parent_event_id=parent_event_id,
            data=data or {},
        )


# ==================== 具体事件类型 ====================
class TaskQueuedEvent(BaseTaskEvent):
    """任务已入队事件"""

    pass


class TaskStartedEvent(BaseTaskEvent):
    """任务已开始事件"""

    pass


class RequirementClarificationRequestedEvent(BaseTaskEvent):
    """需求澄清请求事件"""

    # data 包含：
    # - questions: [{id, type, text, priority, is_required}]
    # - round_number: int


class RequirementClarificationReceivedEvent(BaseTaskEvent):
    """需求澄清已接收事件"""

    # data 包含：
    # - round_number: int
    # - user_response: str


class SkillSelectedEvent(BaseTaskEvent):
    """已选择 Skill 事件"""

    # data 包含：
    # - skill_name: str
    # - confidence: float
    # - reasoning: str


class PlanCreatedEvent(BaseTaskEvent):
    """已生成计划事件"""

    # data 包含：
    # - steps: [{index, title, description, action_type, parameters}]
    # - estimated_tokens: int
    # - estimated_duration_seconds: int


class StepStartedEvent(BaseTaskEvent):
    """步骤开始事件"""

    # data 包含：
    # - step_index: int
    # - step_title: str


class StepCompletedEvent(BaseTaskEvent):
    """步骤完成事件"""

    # data 包含：
    # - step_index: int
    # - result: str


class ToolStartedEvent(BaseTaskEvent):
    """Tool 开始执行事件"""

    # data 包含：
    # - tool_name: str
    # - parameters: dict


class ToolCompletedEvent(BaseTaskEvent):
    """Tool 完成事件"""

    # data 包含：
    # - tool_name: str
    # - result: dict
    # - duration_ms: int


class SubAgentStartedEvent(BaseTaskEvent):
    """子 Agent 开始事件"""

    # data 包含：
    # - agent_name: str
    # - input_data: dict


class SubAgentCompletedEvent(BaseTaskEvent):
    """子 Agent 完成事件"""

    # data 包含：
    # - agent_name: str
    # - result: dict
    # - trace_id: str


class VerificationFailedEvent(BaseTaskEvent):
    """验证失败事件"""

    # data 包含：
    # - issues: [{issue_type, message, severity, suggestion}]
    # - can_retry: bool
    # - suggestion: str


class ArtifactCreatedEvent(BaseTaskEvent):
    """Artifact 已生成事件"""

    # data 包含：
    # - artifact_id: str
    # - artifact_type: str
    # - url: str


class TaskCompletedEvent(BaseTaskEvent):
    """任务完成事件"""

    # data 包含：
    # - result: str
    # - artifacts: [{id, type, url}]
    # - citations: [{id, source, page}]


class TaskFailedEvent(BaseTaskEvent):
    """任务失败事件"""

    # data 包含：
    # - error_code: str
    # - error_message: str
    # - details: dict


class TaskCancelledEvent(BaseTaskEvent):
    """任务已取消事件"""

    # data 包含：
    # - reason: str


# ==================== 事件发送者 ====================
class EventSender:
    """事件发送工具

    用于一致地创建和格式化事件。
    """

    def __init__(self, task_id: str, trace_id: Optional[str] = None):
        self.task_id = task_id
        self.trace_id = trace_id
        self.sequence_counter = 0
        self.parent_event_id: Optional[str] = None

    def _next_sequence(self) -> int:
        """获取下一个 sequence 号"""
        self.sequence_counter += 1
        return self.sequence_counter

    def task_queued(self) -> BaseTaskEvent:
        """任务已入队"""
        return TaskQueuedEvent.create(
            task_id=self.task_id,
            event_type=TaskEventType.TASK_QUEUED,
            sequence=self._next_sequence(),
            trace_id=self.trace_id,
        )

    def task_started(self) -> BaseTaskEvent:
        """任务已开始"""
        return TaskStartedEvent.create(
            task_id=self.task_id,
            event_type=TaskEventType.TASK_STARTED,
            sequence=self._next_sequence(),
            trace_id=self.trace_id,
        )

    def skill_selected(
        self, skill_name: str, confidence: float, reasoning: str
    ) -> BaseTaskEvent:
        """已选择 Skill"""
        event = SkillSelectedEvent.create(
            task_id=self.task_id,
            event_type=TaskEventType.SKILL_SELECTED,
            sequence=self._next_sequence(),
            data={
                "skill_name": skill_name,
                "confidence": confidence,
                "reasoning": reasoning,
            },
            trace_id=self.trace_id,
        )
        self.parent_event_id = event.event_id
        return event

    def task_completed(
        self, result: str, artifacts: list = None, citations: list = None
    ) -> BaseTaskEvent:
        """任务完成"""
        return TaskCompletedEvent.create(
            task_id=self.task_id,
            event_type=TaskEventType.TASK_COMPLETED,
            sequence=self._next_sequence(),
            data={
                "result": result,
                "artifacts": artifacts or [],
                "citations": citations or [],
            },
            trace_id=self.trace_id,
        )

    def task_failed(
        self, error_code: str, error_message: str, details: dict = None
    ) -> BaseTaskEvent:
        """任务失败"""
        return TaskFailedEvent.create(
            task_id=self.task_id,
            event_type=TaskEventType.TASK_FAILED,
            sequence=self._next_sequence(),
            data={
                "error_code": error_code,
                "error_message": error_message,
                "details": details or {},
            },
            trace_id=self.trace_id,
        )
