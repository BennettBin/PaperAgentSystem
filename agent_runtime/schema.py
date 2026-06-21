"""
Agent Runtime Schema 和数据模型

定义 Agent 运行时的所有 Schema，确保前后端通信一致。
"""

from dataclasses import dataclass, field
from typing import Optional, Any
from datetime import datetime
from enum import Enum

from core.domain.ids import TaskId, TraceId


# ==================== Agent 状态 ====================
class AgentState(str, Enum):
    """Agent 任务状态"""

    RECEIVED = "received"
    UNDERSTANDING = "understanding"
    REQUIREMENT_CHECK = "requirement_check"
    CLARIFYING = "clarifying"
    WAITING_USER = "waiting_user"
    SKILL_SELECTED = "skill_selected"
    PLANNED = "planned"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REPLANNING = "replanning"


# ==================== 需求检查 ====================
@dataclass
class RequirementCheckResult:
    """需求检查结果"""

    status: str  # "sufficient" / "needs_clarification"
    sufficient_info: bool
    missing_fields: list[str] = field(default_factory=list)
    constraints: dict = field(default_factory=dict)
    inferred_skill: Optional[str] = None
    confidence: float = 0.0


@dataclass
class ClarificationQuestion:
    """澄清问题"""

    id: str
    type: str  # "missing_info", "ambiguous", "scope", "constraint"
    text: str
    priority: int  # 1-5, 1 最高
    is_required: bool = True


@dataclass
class ClarificationRequest:
    """澄清请求"""

    questions: list[ClarificationQuestion]
    round_number: int


# ==================== Skill 选择 ====================
@dataclass
class SkillSelectionResult:
    """Skill 选择结果"""

    skill_name: str
    confidence: float
    reasoning: str
    alternatives: list[tuple[str, float]] = field(default_factory=list)


# ==================== 规划 ====================
@dataclass
class PlanStep:
    """计划步骤"""

    index: int
    title: str
    description: str
    action_type: str  # "tool_call", "generate", "verify", etc.
    parameters: dict
    dependencies: list[int] = field(default_factory=list)


@dataclass
class Plan:
    """执行计划"""

    steps: list[PlanStep] = field(default_factory=list)
    estimated_tokens: int = 0
    estimated_duration_seconds: int = 0
    strategy: str = ""  # 执行策略说明


# ==================== Tool 调用 ====================
@dataclass
class ToolCallRequest:
    """Tool 调用请求"""

    tool_name: str
    parameters: dict
    timeout_seconds: int = 30


@dataclass
class ToolCallResult:
    """Tool 调用结果"""

    tool_name: str
    success: bool
    result: Optional[dict] = None
    error: Optional[str] = None
    duration_ms: int = 0


# ==================== 子 Agent ====================
@dataclass
class SubAgentRequest:
    """子 Agent 请求"""

    agent_name: str  # "paper_reader_agent", etc.
    input_data: dict
    timeout_seconds: int = 300
    model_profile: Optional[str] = None


@dataclass
class SubAgentResult:
    """子 Agent 结果"""

    agent_name: str
    success: bool
    result: Optional[dict] = None
    error: Optional[str] = None
    trace_id: Optional[str] = None


# ==================== 验证 ====================
class VerificationStatus(str, Enum):
    """验证状态"""

    PASSED = "passed"
    FAILED = "failed"
    PARTIAL = "partial"


@dataclass
class VerificationIssue:
    """验证问题"""

    issue_type: str  # "schema_violation", "missing_evidence", "contradiction", etc.
    message: str
    severity: str  # "error", "warning", "info"
    suggestion: Optional[str] = None


@dataclass
class VerificationResult:
    """验证结果"""

    status: VerificationStatus
    is_valid: bool
    issues: list[VerificationIssue] = field(default_factory=list)
    can_retry: bool = True
    suggestion: Optional[str] = None


# ==================== 最终响应 ====================
@dataclass
class FinalResponse:
    """最终响应"""

    content: str
    artifacts: list[dict] = field(default_factory=list)
    citations: list[dict] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


# ==================== 决策 ====================
@dataclass
class AgentDecision:
    """Agent 做出的决策"""

    task_id: TaskId
    decision_type: str  # "next_state", "clarify", "execute", "verify", "complete", etc.
    data: dict
    timestamp: datetime = field(default_factory=datetime.utcnow)
    reasoning: Optional[str] = None


# ==================== 预算和限制 ====================
@dataclass
class ExecutionBudget:
    """执行预算"""

    max_tokens: int
    max_steps: int
    max_duration_seconds: int
    max_parallel_tasks: int
    tokens_used: int = 0
    steps_executed: int = 0
    start_time: datetime = field(default_factory=datetime.utcnow)

    def is_exceeded(self) -> dict[str, bool]:
        """检查是否超过预算"""
        duration = (datetime.utcnow() - self.start_time).total_seconds()
        return {
            "tokens": self.tokens_used >= self.max_tokens,
            "steps": self.steps_executed >= self.max_steps,
            "duration": duration >= self.max_duration_seconds,
        }


# ==================== Context 构建 ====================
@dataclass
class AgentContext:
    """Agent 执行上下文"""

    task_id: TaskId
    state: AgentState
    requirement_brief: Optional[RequirementCheckResult] = None
    selected_skill: Optional[SkillSelectionResult] = None
    plan: Optional[Plan] = None
    executed_steps: list[dict] = field(default_factory=list)
    tool_results: list[ToolCallResult] = field(default_factory=list)
    budget: ExecutionBudget = field(default_factory=lambda: ExecutionBudget(
        max_tokens=8000,
        max_steps=8,
        max_duration_seconds=300,
        max_parallel_tasks=3,
    ))
    trace_id: Optional[TraceId] = None
    metadata: dict = field(default_factory=dict)
