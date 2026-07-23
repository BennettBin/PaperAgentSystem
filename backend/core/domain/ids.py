"""
强类型 ID 定义

避免在模块间传递无类型的字符串 ID。
每个实体都有对应的强类型 ID 类。
"""

from typing import Self
from uuid import uuid4

from pydantic import BaseModel, Field


class BaseId(BaseModel):
    """基类，所有 ID 都继承此类"""

    value: str = Field(..., description="UUID 字符串")

    def __str__(self) -> str:
        return self.value

    def __eq__(self, other: object) -> bool:
        if isinstance(other, BaseId):
            return self.value == other.value
        return False

    def __hash__(self) -> int:
        return hash(self.value)

    @classmethod
    def generate(cls) -> Self:
        """生成新 ID"""
        return cls(value=str(uuid4()))

    def to_str(self) -> str:
        return self.value


# 用户和权限相关 ID
class UserId(BaseId):
    """用户 ID"""

    pass


class WorkspaceId(BaseId):
    """工作区 ID"""

    pass


class PermissionId(BaseId):
    """权限 ID"""

    pass


# 对话相关 ID
class ConversationId(BaseId):
    """对话 ID"""

    pass


class MessageId(BaseId):
    """消息 ID"""

    pass


class ConversationFileId(BaseId):
    """对话文件关联 ID"""

    pass


# 任务相关 ID
class TaskId(BaseId):
    """任务 ID"""

    pass


class StepId(BaseId):
    """步骤 ID"""

    pass


class PlanId(BaseId):
    """计划 ID"""

    pass


class ToolCallId(BaseId):
    """Tool 调用 ID"""

    pass


class SubAgentRunId(BaseId):
    """子 Agent 运行 ID"""

    pass


# 文件相关 ID
class FileId(BaseId):
    """文件 ID"""

    pass


class WorkspaceEntryId(BaseId):
    """工作空间条目 ID"""

    pass


class ClarificationRoundId(BaseId):
    """澄清轮次 ID"""

    pass


# 技能和工具相关 ID
class SkillDefinitionId(BaseId):
    """Skill 定义 ID"""

    pass


class ToolDefinitionId(BaseId):
    """Tool 定义 ID"""

    pass


# 文档和记忆相关 ID
class DocumentId(BaseId):
    """文档 ID"""

    pass


class ChunkId(BaseId):
    """文本块 ID"""

    pass


class MemorySegmentId(BaseId):
    """记忆段 ID"""

    pass


class ConversationSummaryId(BaseId):
    """对话摘要 ID"""

    pass


class MemoryPreferenceId(BaseId):
    """记忆偏好 ID"""

    pass


# 工作空间相关 ID
class ConversationWorkspaceId(BaseId):
    """对话工作空间 ID"""

    pass


class TaskWorkspaceId(BaseId):
    """任务工作空间 ID"""

    pass


# 模型和评估相关 ID
class ModelProfileId(BaseId):
    """模型 Profile ID"""

    pass


class ModelVersionId(BaseId):
    """模型版本 ID"""

    pass


class EvaluationRunId(BaseId):
    """评估运行 ID"""

    pass


# Trace 和观测相关 ID
class TraceId(BaseId):
    """Trace ID"""

    pass


class EventId(BaseId):
    """事件 ID"""

    pass


class ArtifactId(BaseId):
    """Artifact ID"""

    pass


class CitationId(BaseId):
    """引用 ID"""

    pass
