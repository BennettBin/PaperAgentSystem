"""
全局枚举定义

包含系统中的所有状态、角色和类型。
"""

from enum import Enum


# ==================== Task 和 Step 状态 ====================
class TaskStatus(str, Enum):
    """任务状态"""

    RECEIVED = "received"  # 任务已接收
    UNDERSTANDING = "understanding"  # 正在理解需求
    REQUIREMENT_CHECK = "requirement_check"  # 进行需求检查
    CLARIFYING = "clarifying"  # 需要澄清
    WAITING_USER = "waiting_user"  # 等待用户回答
    SKILL_SELECTED = "skill_selected"  # 已选择 Skill
    PLANNED = "planned"  # 已生成计划
    EXECUTING = "executing"  # 正在执行
    VERIFYING = "verifying"  # 正在验证
    COMPLETED = "completed"  # 已完成
    FAILED = "failed"  # 失败
    CANCELLED = "cancelled"  # 已取消
    REPLANNING = "replanning"  # 重新规划


class StepStatus(str, Enum):
    """步骤状态"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


# ==================== 消息和通信 ====================
class MessageRole(str, Enum):
    """消息角色"""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class MessageType(str, Enum):
    """消息类型"""

    TEXT = "text"
    FILE = "file"
    ARTIFACT = "artifact"
    CLARIFICATION = "clarification"
    TASK_EVENT = "task_event"


# ==================== 工作空间 ====================
class WorkspaceEntryKind(str, Enum):
    """工作空间条目类型"""

    FILE = "file"
    DIRECTORY = "directory"
    ARTIFACT = "artifact"


class WorkspaceEntryRetention(str, Enum):
    """工作空间条目保留策略"""

    PERMANENT = "permanent"  # 永久保留
    SESSION = "session"  # 会话期间保留
    TASK = "task"  # 任务期间保留
    TEMPORARY = "temporary"  # 临时（任务完成后清理）


# ==================== Tool 和 Skill ====================
class ToolPermission(str, Enum):
    """Tool 权限"""

    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    NETWORK = "network"
    DELETE = "delete"


class SkillStatus(str, Enum):
    """Skill 状态"""

    REGISTERED = "registered"
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    DISABLED = "disabled"


# ==================== 模型 ====================
class ModelProfileStatus(str, Enum):
    """模型 Profile 状态"""

    DEVELOPMENT = "development"
    EVALUATION = "evaluation"
    PRODUCTION = "production"
    DEPRECATED = "deprecated"


# ==================== 需求和澄清 ====================
class ClarificationQuestionType(str, Enum):
    """澄清问题类型"""

    MISSING_INFO = "missing_info"
    AMBIGUOUS = "ambiguous"
    SCOPE = "scope"
    CONSTRAINT = "constraint"


class RequirementCheckStatus(str, Enum):
    """需求检查状态"""

    SUFFICIENT = "sufficient"  # 信息充分
    NEEDS_CLARIFICATION = "needs_clarification"  # 需要澄清
    DEFERRED = "deferred"  # 延后判断


# ==================== 验证和错误 ====================
class VerificationStatus(str, Enum):
    """验证状态"""

    PASSED = "passed"
    FAILED = "failed"
    NEEDS_REVISION = "needs_revision"
    PARTIAL = "partial"


class VerificationErrorType(str, Enum):
    """验证错误类型"""

    SCHEMA_VIOLATION = "schema_violation"
    MISSING_EVIDENCE = "missing_evidence"
    CONTRADICTION = "contradiction"
    INCOMPLETE = "incomplete"
    STYLE_ISSUE = "style_issue"


# ==================== 文件和文档 ====================
class DocumentFormat(str, Enum):
    """文档格式"""

    PDF = "pdf"
    DOCX = "docx"
    MARKDOWN = "markdown"
    LATEX = "latex"
    PLAIN_TEXT = "plain_text"
    HTML = "html"


class ParseQuality(str, Enum):
    """解析质量"""

    EXCELLENT = "excellent"  # >= 95%
    GOOD = "good"  # 80-95%
    FAIR = "fair"  # 60-80%
    POOR = "poor"  # < 60%


class OCRNeeded(str, Enum):
    """是否需要 OCR"""

    NOT_NEEDED = "not_needed"
    RECOMMENDED = "recommended"
    REQUIRED = "required"


# ==================== 记忆 ====================
class MemoryType(str, Enum):
    """记忆类型"""

    SHORT_TERM = "short_term"  # 当前对话短期记忆
    LONG_TERM = "long_term"  # 跨对话长期记忆
    SEMANTIC = "semantic"  # 语义记忆（知识）


# ==================== 评估 ====================
class EvaluationMetricType(str, Enum):
    """评估指标类型"""

    ACCURACY = "accuracy"
    RECALL = "recall"
    PRECISION = "precision"
    F1 = "f1"
    BLEU = "bleu"
    ROUGE = "rouge"
    MRR = "mrr"
    CUSTOM = "custom"


# ==================== SSE 事件 ====================
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


# ==================== 删除和生命周期 ====================
class DeletionStatus(str, Enum):
    """删除状态"""

    ACTIVE = "active"
    SOFT_DELETED = "soft_deleted"
    HARD_DELETED = "hard_deleted"
