"""
Domain 模块初始化

导出所有 Domain 实体。
"""

from .conversation import Conversation, ConversationFile, Message
from .file import File
from .requirement import ClarificationQuestion, ClarificationRound, RequirementBrief
from .task import Plan, Step, Task, ToolCall
from .user import User, Workspace

__all__ = [
    # User & Workspace
    "User",
    "Workspace",
    # Conversation & Message
    "Conversation",
    "Message",
    "ConversationFile",
    # Task & Plan & Step
    "Task",
    "Plan",
    "Step",
    "ToolCall",
    # File
    "File",
    # Requirement & Clarification
    "RequirementBrief",
    "ClarificationQuestion",
    "ClarificationRound",
]
