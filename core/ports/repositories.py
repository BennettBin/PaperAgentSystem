"""
Repository Port 定义

所有数据访问必须通过这些接口。
"""

from abc import ABC, abstractmethod
from typing import Optional, Sequence

from core.domain.ids import (
    ConversationId,
    FileId,
    MessageId,
    TaskId,
    UserId,
    WorkspaceId,
)
from core.domain.conversation import Conversation, Message
from core.domain.task import Task
from core.domain.file import File
from core.domain.user import User, Workspace


class ConversationRepository(ABC):
    """对话仓储"""

    @abstractmethod
    async def save(self, conversation: Conversation) -> None:
        """保存对话"""
        pass

    @abstractmethod
    async def find_by_id(
        self, conv_id: ConversationId, workspace_id: WorkspaceId
    ) -> Optional[Conversation]:
        """按 ID 查找对话"""
        pass

    @abstractmethod
    async def list_by_workspace(
        self, workspace_id: WorkspaceId, skip: int = 0, limit: int = 50
    ) -> Sequence[Conversation]:
        """列出工作区内的对话"""
        pass

    @abstractmethod
    async def delete(self, conv_id: ConversationId, workspace_id: WorkspaceId) -> bool:
        """删除对话"""
        pass


class MessageRepository(ABC):
    """消息仓储"""

    @abstractmethod
    async def save(self, message: Message) -> None:
        """保存消息"""
        pass

    @abstractmethod
    async def find_by_id(
        self, msg_id: MessageId, workspace_id: WorkspaceId
    ) -> Optional[Message]:
        """按 ID 查找消息"""
        pass

    @abstractmethod
    async def list_by_conversation(
        self,
        conv_id: ConversationId,
        workspace_id: WorkspaceId,
        skip: int = 0,
        limit: int = 50,
    ) -> Sequence[Message]:
        """列出对话内的消息"""
        pass

    @abstractmethod
    async def delete(self, msg_id: MessageId, workspace_id: WorkspaceId) -> bool:
        """删除消息"""
        pass


class TaskRepository(ABC):
    """任务仓储"""

    @abstractmethod
    async def save(self, task: Task) -> None:
        """保存任务"""
        pass

    @abstractmethod
    async def find_by_id(
        self, task_id: TaskId, workspace_id: WorkspaceId
    ) -> Optional[Task]:
        """按 ID 查找任务"""
        pass

    @abstractmethod
    async def list_by_conversation(
        self,
        conv_id: ConversationId,
        workspace_id: WorkspaceId,
        skip: int = 0,
        limit: int = 50,
    ) -> Sequence[Task]:
        """列出对话内的任务"""
        pass

    @abstractmethod
    async def list_by_workspace(
        self, workspace_id: WorkspaceId, skip: int = 0, limit: int = 50
    ) -> Sequence[Task]:
        """列出工作区内的任务"""
        pass


class FileRepository(ABC):
    """文件仓储"""

    @abstractmethod
    async def save(self, file: File) -> None:
        """保存文件元数据"""
        pass

    @abstractmethod
    async def find_by_id(
        self, file_id: FileId, workspace_id: WorkspaceId
    ) -> Optional[File]:
        """按 ID 查找文件"""
        pass

    @abstractmethod
    async def list_by_workspace(
        self, workspace_id: WorkspaceId, skip: int = 0, limit: int = 50
    ) -> Sequence[File]:
        """列出工作区内的文件"""
        pass

    @abstractmethod
    async def delete(self, file_id: FileId, workspace_id: WorkspaceId) -> bool:
        """删除文件"""
        pass


class UserRepository(ABC):
    """用户仓储"""

    @abstractmethod
    async def save(self, user: User) -> None:
        """保存用户"""
        pass

    @abstractmethod
    async def find_by_id(self, user_id: UserId) -> Optional[User]:
        """按 ID 查找用户"""
        pass

    @abstractmethod
    async def find_by_email(self, email: str) -> Optional[User]:
        """按邮箱查找用户"""
        pass


class WorkspaceRepository(ABC):
    """工作区仓储"""

    @abstractmethod
    async def save(self, workspace: Workspace) -> None:
        """保存工作区"""
        pass

    @abstractmethod
    async def find_by_id(
        self, workspace_id: WorkspaceId, user_id: UserId
    ) -> Optional[Workspace]:
        """按 ID 查找工作区"""
        pass

    @abstractmethod
    async def list_by_user(
        self, user_id: UserId, skip: int = 0, limit: int = 50
    ) -> Sequence[Workspace]:
        """列出用户的工作区"""
        pass

    @abstractmethod
    async def verify_workspace_access(
        self, workspace_id: WorkspaceId, user_id: UserId
    ) -> bool:
        """验证用户对工作区的访问权限"""
        pass
