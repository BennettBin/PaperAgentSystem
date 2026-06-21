"""
对话和消息实体
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Optional

from core.domain.enums import MessageRole, MessageType
from core.domain.ids import (
    ConversationFileId,
    ConversationId,
    FileId,
    MessageId,
    UserId,
    WorkspaceId,
)


@dataclass
class Conversation:
    """对话实体

    代表用户与系统的一次对话会话。
    """

    id: ConversationId
    workspace_id: WorkspaceId
    user_id: UserId
    title: str
    description: Optional[str]
    created_at: datetime
    updated_at: datetime
    is_archived: bool = False

    @classmethod
    def create(
        cls,
        workspace_id: WorkspaceId,
        user_id: UserId,
        title: str,
        description: Optional[str] = None,
    ) -> "Conversation":
        """创建新对话"""
        now = datetime.now(UTC)
        return cls(
            id=ConversationId.generate(),
            workspace_id=workspace_id,
            user_id=user_id,
            title=title,
            description=description,
            created_at=now,
            updated_at=now,
        )


@dataclass
class Message:
    """消息实体

    对话中的单条消息。
    """

    id: MessageId
    conversation_id: ConversationId
    role: MessageRole
    type: MessageType
    content: str
    metadata: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def create_user_message(
        cls,
        conversation_id: ConversationId,
        content: str,
        metadata: Optional[dict] = None,
    ) -> "Message":
        """创建用户消息"""
        return cls(
            id=MessageId.generate(),
            conversation_id=conversation_id,
            role=MessageRole.USER,
            type=MessageType.TEXT,
            content=content,
            metadata=metadata or {},
        )

    @classmethod
    def create_assistant_message(
        cls,
        conversation_id: ConversationId,
        content: str,
        metadata: Optional[dict] = None,
    ) -> "Message":
        """创建助手消息"""
        return cls(
            id=MessageId.generate(),
            conversation_id=conversation_id,
            role=MessageRole.ASSISTANT,
            type=MessageType.TEXT,
            content=content,
            metadata=metadata or {},
        )


@dataclass
class ConversationFile:
    """对话-文件关联

    表示用户在对话中上传或引用的文件。
    """

    id: ConversationFileId
    conversation_id: ConversationId
    file_id: FileId
    uploaded_by_user: bool
    uploaded_at: datetime
    metadata: dict = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        conversation_id: ConversationId,
        file_id: FileId,
        uploaded_by_user: bool = True,
        metadata: Optional[dict] = None,
    ) -> "ConversationFile":
        """创建文件关联"""
        return cls(
            id=ConversationFileId.generate(),
            conversation_id=conversation_id,
            file_id=file_id,
            uploaded_by_user=uploaded_by_user,
            uploaded_at=datetime.now(UTC),
            metadata=metadata or {},
        )
