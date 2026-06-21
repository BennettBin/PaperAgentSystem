"""
Fake Repository implementations for development and testing
"""

from typing import List, Optional

from core.domain.conversation import Conversation, Message
from core.domain.file import File
from core.domain.ids import ConversationId, FileId, MessageId, TaskId, UserId, WorkspaceId
from core.domain.task import Task
from core.domain.user import Workspace
from core.ports.repositories import (
    ConversationRepository,
    FileRepository,
    MessageRepository,
    TaskRepository,
    WorkspaceRepository,
)


class FakeConversationRepository(ConversationRepository):
    def __init__(self):
        self.conversations: dict[str, Conversation] = {}

    async def save(self, conversation: Conversation) -> None:
        self.conversations[str(conversation.id)] = conversation

    async def find_by_id(
        self, conversation_id: ConversationId, workspace_id: WorkspaceId
    ) -> Optional[Conversation]:
        conv = self.conversations.get(str(conversation_id))
        if conv and conv.workspace_id == workspace_id:
            return conv
        return None

    async def list_by_workspace(
        self, workspace_id: WorkspaceId, skip: int = 0, limit: int = 10
    ) -> List[Conversation]:
        return [c for c in self.conversations.values() if c.workspace_id == workspace_id][
            skip : skip + limit
        ]

    async def delete(self, conversation_id: ConversationId, workspace_id: WorkspaceId) -> bool:
        conv = self.conversations.pop(str(conversation_id), None)
        return conv is not None and conv.workspace_id == workspace_id


class FakeMessageRepository(MessageRepository):
    def __init__(self):
        self.messages: dict[str, Message] = {}

    async def save(self, message: Message) -> None:
        self.messages[str(message.id)] = message

    async def find_by_id(
        self, message_id: MessageId, workspace_id: WorkspaceId
    ) -> Optional[Message]:
        msg = self.messages.get(str(message_id))
        if msg and msg.conversation_id:
            return msg
        return None

    async def list_by_conversation(
        self,
        conversation_id: ConversationId,
        workspace_id: WorkspaceId,
        skip: int = 0,
        limit: int = 50,
    ) -> List[Message]:
        return [m for m in self.messages.values() if m.conversation_id == conversation_id][
            skip : skip + limit
        ]

    async def delete(self, message_id: MessageId, workspace_id: WorkspaceId) -> bool:
        msg = self.messages.pop(str(message_id), None)
        return msg is not None


class FakeTaskRepository(TaskRepository):
    def __init__(self):
        self.tasks: dict[str, Task] = {}

    async def save(self, task: Task) -> None:
        self.tasks[str(task.id)] = task

    async def find_by_id(self, task_id: TaskId, workspace_id: WorkspaceId) -> Optional[Task]:
        task = self.tasks.get(str(task_id))
        if task and task.workspace_id == workspace_id:
            return task
        return None

    async def list_by_workspace(
        self, workspace_id: WorkspaceId, skip: int = 0, limit: int = 20
    ) -> List[Task]:
        return [t for t in self.tasks.values() if t.workspace_id == workspace_id][
            skip : skip + limit
        ]

    async def list_by_conversation(
        self, conversation_id, workspace_id: WorkspaceId, skip: int = 0, limit: int = 20
    ) -> List[Task]:
        return []

    async def update_status(
        self, task_id: TaskId, workspace_id: WorkspaceId, new_status: str
    ) -> bool:
        task = self.tasks.get(str(task_id))
        if task and task.workspace_id == workspace_id:
            return True
        return False


class FakeFileRepository(FileRepository):
    def __init__(self):
        self.files: dict[str, File] = {}

    async def save(self, file: File) -> None:
        self.files[str(file.id)] = file

    async def find_by_id(self, file_id: FileId, workspace_id: WorkspaceId) -> Optional[File]:
        file = self.files.get(str(file_id))
        if file and file.workspace_id == workspace_id:
            return file
        return None

    async def list_by_workspace(
        self, workspace_id: WorkspaceId, skip: int = 0, limit: int = 20
    ) -> List[File]:
        return [f for f in self.files.values() if f.workspace_id == workspace_id][
            skip : skip + limit
        ]

    async def delete(self, file_id: FileId, workspace_id: WorkspaceId) -> bool:
        file = self.files.pop(str(file_id), None)
        return file is not None and file.workspace_id == workspace_id


class FakeWorkspaceRepository(WorkspaceRepository):
    def __init__(self):
        self.workspaces: dict[str, Workspace] = {}

    async def save(self, workspace: Workspace) -> None:
        self.workspaces[str(workspace.id)] = workspace

    async def find_by_id(self, workspace_id: WorkspaceId, user_id: UserId) -> Optional[Workspace]:
        ws = self.workspaces.get(str(workspace_id))
        if ws and ws.user_id == user_id:
            return ws
        return None

    async def list_by_user(
        self, user_id: UserId, skip: int = 0, limit: int = 20
    ) -> List[Workspace]:
        return [ws for ws in self.workspaces.values() if ws.user_id == user_id][skip : skip + limit]

    async def delete(self, workspace_id: WorkspaceId, user_id: UserId) -> bool:
        ws = self.workspaces.pop(str(workspace_id), None)
        return ws is not None and ws.user_id == user_id

    async def verify_workspace_access(self, workspace_id: WorkspaceId, user_id: UserId) -> bool:
        ws = self.workspaces.get(str(workspace_id))
        return ws is not None and ws.user_id == user_id
