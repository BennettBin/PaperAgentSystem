from datetime import datetime
from uuid import uuid4

from sqlalchemy import Select, func, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from core.domain.conversation import Conversation, Message
from core.domain.enums import MessageRole, MessageType, TaskStatus
from core.domain.file import File
from core.domain.ids import (
    ConversationId,
    FileId,
    MessageId,
    TaskId,
    TraceId,
    UserId,
    WorkspaceId,
)
from core.domain.task import Task
from core.domain.user import User, Workspace
from core.ports.repositories import (
    ConversationRepository,
    FileRepository,
    MessageRepository,
    TaskRepository,
    UserRepository,
    WorkspaceRepository,
)
from infrastructure.postgres.models import (
    ConversationModel,
    FileModel,
    MessageFileModel,
    MessageModel,
    TaskModel,
    UserModel,
    WorkspaceModel,
    utc_now,
)


class SqlAlchemyUserRepository(UserRepository):
    def __init__(self, session: Session) -> None:
        self.session = session

    async def save(self, user: User) -> None:
        model = self.session.get(UserModel, str(user.id)) or UserModel(id=str(user.id))
        model.email, model.name, model.is_active = user.email, user.name, user.is_active
        model.created_at, model.updated_at = user.created_at, user.updated_at
        self.session.add(model)

    async def find_by_id(self, user_id: UserId) -> User | None:
        model = self.session.scalar(
            select(UserModel).where(UserModel.id == str(user_id), UserModel.deleted_at.is_(None))
        )
        return _user(model)

    async def find_by_email(self, email: str) -> User | None:
        model = self.session.scalar(
            select(UserModel).where(UserModel.email == email, UserModel.deleted_at.is_(None))
        )
        return _user(model)


class SqlAlchemyWorkspaceRepository(WorkspaceRepository):
    def __init__(self, session: Session) -> None:
        self.session = session

    async def save(self, workspace: Workspace) -> None:
        model = self.session.get(WorkspaceModel, str(workspace.id)) or WorkspaceModel(
            id=str(workspace.id), user_id=str(workspace.user_id)
        )
        model.user_id, model.name = str(workspace.user_id), workspace.name
        model.description, model.is_active = workspace.description, workspace.is_active
        model.created_at, model.updated_at = workspace.created_at, workspace.updated_at
        self.session.add(model)

    async def find_by_id(self, workspace_id: WorkspaceId, user_id: UserId) -> Workspace | None:
        model = self.session.scalar(
            select(WorkspaceModel).where(
                WorkspaceModel.id == str(workspace_id),
                WorkspaceModel.user_id == str(user_id),
                WorkspaceModel.deleted_at.is_(None),
            )
        )
        return _workspace(model)

    async def list_by_user(
        self, user_id: UserId, skip: int = 0, limit: int = 50
    ) -> list[Workspace]:
        models = self.session.scalars(
            select(WorkspaceModel)
            .where(
                WorkspaceModel.user_id == str(user_id),
                WorkspaceModel.deleted_at.is_(None),
            )
            .order_by(WorkspaceModel.created_at)
            .offset(skip)
            .limit(limit)
        )
        return [value for model in models if (value := _workspace(model)) is not None]

    async def verify_workspace_access(self, workspace_id: WorkspaceId, user_id: UserId) -> bool:
        return await self.find_by_id(workspace_id, user_id) is not None


class SqlAlchemyConversationRepository(ConversationRepository):
    def __init__(self, session: Session) -> None:
        self.session = session

    async def save(self, conversation: Conversation) -> None:
        model = self.session.get(ConversationModel, str(conversation.id)) or ConversationModel(
            id=str(conversation.id),
            workspace_id=str(conversation.workspace_id),
            user_id=str(conversation.user_id),
        )
        model.title, model.description = conversation.title, conversation.description
        model.is_archived = conversation.is_archived
        model.created_at, model.updated_at = conversation.created_at, conversation.updated_at
        self.session.add(model)

    async def find_by_id(
        self, conv_id: ConversationId, workspace_id: WorkspaceId
    ) -> Conversation | None:
        return _conversation(
            self.session.scalar(
                select(ConversationModel).where(
                    ConversationModel.id == str(conv_id),
                    ConversationModel.workspace_id == str(workspace_id),
                    ConversationModel.deleted_at.is_(None),
                )
            )
        )

    async def list_by_workspace(
        self, workspace_id: WorkspaceId, skip: int = 0, limit: int = 50
    ) -> list[Conversation]:
        models = self.session.scalars(
            select(ConversationModel)
            .where(
                ConversationModel.workspace_id == str(workspace_id),
                ConversationModel.deleted_at.is_(None),
            )
            .order_by(ConversationModel.updated_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return [value for model in models if (value := _conversation(model)) is not None]

    async def search(
        self, workspace_id: WorkspaceId, query: str, skip: int = 0, limit: int = 50
    ) -> list[Conversation]:
        statement = select(ConversationModel).where(
            ConversationModel.workspace_id == str(workspace_id),
            ConversationModel.deleted_at.is_(None),
        )
        if query:
            pattern = f"%{query.lower()}%"
            statement = statement.where(
                or_(
                    func.lower(ConversationModel.title).like(pattern),
                    func.lower(ConversationModel.description).like(pattern),
                )
            )
        models = self.session.scalars(
            statement.order_by(ConversationModel.updated_at.desc(), ConversationModel.id.desc())
            .offset(skip)
            .limit(limit)
        )
        return [value for model in models if (value := _conversation(model)) is not None]

    async def delete(self, conv_id: ConversationId, workspace_id: WorkspaceId) -> bool:
        model = self.session.scalar(
            select(ConversationModel).where(
                ConversationModel.id == str(conv_id),
                ConversationModel.workspace_id == str(workspace_id),
                ConversationModel.deleted_at.is_(None),
            )
        )
        if model is None:
            return False
        model.deleted_at = utc_now()
        self.session.execute(
            update(MessageModel)
            .where(
                MessageModel.conversation_id == str(conv_id),
                MessageModel.workspace_id == str(workspace_id),
                MessageModel.deleted_at.is_(None),
            )
            .values(deleted_at=utc_now())
        )
        return True


class SqlAlchemyMessageRepository(MessageRepository):
    def __init__(self, session: Session) -> None:
        self.session = session

    async def save(self, message: Message) -> None:
        conversation = self.session.get(ConversationModel, str(message.conversation_id))
        if conversation is None:
            raise ValueError("Conversation must exist before saving a message")
        model = self.session.get(MessageModel, str(message.id)) or MessageModel(
            id=str(message.id),
            workspace_id=conversation.workspace_id,
            conversation_id=str(message.conversation_id),
        )
        model.role, model.type, model.content = (
            message.role.value,
            message.type.value,
            message.content,
        )
        model.metadata_json, model.created_at = message.metadata, message.created_at
        self.session.add(model)

    async def find_by_id(self, msg_id: MessageId, workspace_id: WorkspaceId) -> Message | None:
        return _message(
            self.session.scalar(
                select(MessageModel).where(
                    MessageModel.id == str(msg_id),
                    MessageModel.workspace_id == str(workspace_id),
                    MessageModel.deleted_at.is_(None),
                )
            )
        )

    async def list_by_conversation(
        self,
        conv_id: ConversationId,
        workspace_id: WorkspaceId,
        skip: int = 0,
        limit: int = 50,
    ) -> list[Message]:
        models = self.session.scalars(
            select(MessageModel)
            .where(
                MessageModel.conversation_id == str(conv_id),
                MessageModel.workspace_id == str(workspace_id),
                MessageModel.deleted_at.is_(None),
            )
            .order_by(MessageModel.created_at)
            .offset(skip)
            .limit(limit)
        )
        return [value for model in models if (value := _message(model)) is not None]

    async def delete(self, msg_id: MessageId, workspace_id: WorkspaceId) -> bool:
        model = self.session.scalar(
            select(MessageModel).where(
                MessageModel.id == str(msg_id),
                MessageModel.workspace_id == str(workspace_id),
                MessageModel.deleted_at.is_(None),
            )
        )
        if model is None:
            return False
        model.deleted_at = utc_now()
        return True

    async def delete_range(
        self,
        conv_id: ConversationId,
        workspace_id: WorkspaceId,
        start: datetime,
        end: datetime,
    ) -> int:
        result: CursorResult = self.session.execute(  # type: ignore[assignment]
            update(MessageModel)
            .where(
                MessageModel.conversation_id == str(conv_id),
                MessageModel.workspace_id == str(workspace_id),
                MessageModel.created_at >= start,
                MessageModel.created_at <= end,
                MessageModel.deleted_at.is_(None),
            )
            .values(deleted_at=utc_now())
        )
        return int(result.rowcount or 0)

    async def attach_file(
        self, message_id: MessageId, file_id: FileId, workspace_id: WorkspaceId
    ) -> None:
        message = self.session.scalar(
            select(MessageModel).where(
                MessageModel.id == str(message_id),
                MessageModel.workspace_id == str(workspace_id),
                MessageModel.deleted_at.is_(None),
            )
        )
        file = self.session.scalar(
            select(FileModel).where(
                FileModel.id == str(file_id),
                FileModel.workspace_id == str(workspace_id),
                FileModel.deleted_at.is_(None),
            )
        )
        if message is None or file is None:
            raise ValueError("Message and file must belong to the same workspace")
        existing = self.session.scalar(
            select(MessageFileModel).where(
                MessageFileModel.message_id == str(message_id),
                MessageFileModel.file_id == str(file_id),
                MessageFileModel.deleted_at.is_(None),
            )
        )
        if existing is None:
            self.session.add(
                MessageFileModel(
                    id=uuid4().hex,
                    workspace_id=str(workspace_id),
                    message_id=str(message_id),
                    file_id=str(file_id),
                )
            )

    async def list_file_ids(self, message_id: MessageId, workspace_id: WorkspaceId) -> list[FileId]:
        ids = self.session.scalars(
            select(MessageFileModel.file_id).where(
                MessageFileModel.message_id == str(message_id),
                MessageFileModel.workspace_id == str(workspace_id),
                MessageFileModel.deleted_at.is_(None),
            )
        )
        return [FileId(value=value) for value in ids]


class SqlAlchemyTaskRepository(TaskRepository):
    def __init__(self, session: Session) -> None:
        self.session = session

    async def save(self, task: Task) -> None:
        model = self.session.get(TaskModel, str(task.id)) or TaskModel(
            id=str(task.id),
            workspace_id=str(task.workspace_id),
            user_id=str(task.user_id),
            conversation_id=str(task.conversation_id),
        )
        model.status, model.input_text = task.status.value, task.input_text
        model.result, model.error_message = task.result, task.error_message
        model.trace_id = str(task.trace_id) if task.trace_id else None
        model.metadata_json = task.metadata
        model.created_at, model.updated_at = task.created_at, task.updated_at
        self.session.add(model)

    async def find_by_id(self, task_id: TaskId, workspace_id: WorkspaceId) -> Task | None:
        return _task(
            self.session.scalar(
                select(TaskModel).where(
                    TaskModel.id == str(task_id),
                    TaskModel.workspace_id == str(workspace_id),
                    TaskModel.deleted_at.is_(None),
                )
            )
        )

    async def list_by_conversation(
        self,
        conv_id: ConversationId,
        workspace_id: WorkspaceId,
        skip: int = 0,
        limit: int = 50,
    ) -> list[Task]:
        statement = select(TaskModel).where(
            TaskModel.conversation_id == str(conv_id),
            TaskModel.workspace_id == str(workspace_id),
            TaskModel.deleted_at.is_(None),
        )
        return self._list(statement, skip, limit)

    async def list_by_workspace(
        self, workspace_id: WorkspaceId, skip: int = 0, limit: int = 50
    ) -> list[Task]:
        statement = select(TaskModel).where(
            TaskModel.workspace_id == str(workspace_id),
            TaskModel.deleted_at.is_(None),
        )
        return self._list(statement, skip, limit)

    def _list(self, statement: Select[tuple[TaskModel]], skip: int, limit: int) -> list[Task]:
        models = self.session.scalars(
            statement.order_by(TaskModel.created_at.desc()).offset(skip).limit(limit)
        )
        return [value for model in models if (value := _task(model)) is not None]


class SqlAlchemyFileRepository(FileRepository):
    def __init__(self, session: Session) -> None:
        self.session = session

    async def save(self, file: File) -> None:
        model = self.session.get(FileModel, str(file.id)) or FileModel(
            id=str(file.id), workspace_id=str(file.workspace_id)
        )
        model.filename, model.content_type = file.filename, file.content_type
        model.size_bytes, model.storage_path = file.size_bytes, file.storage_path
        model.checksum, model.is_deleted = file.checksum, file.is_deleted
        model.metadata_json = file.metadata
        model.created_at, model.updated_at = file.created_at, file.updated_at
        self.session.add(model)

    async def find_by_id(self, file_id: FileId, workspace_id: WorkspaceId) -> File | None:
        return _file(
            self.session.scalar(
                select(FileModel).where(
                    FileModel.id == str(file_id),
                    FileModel.workspace_id == str(workspace_id),
                    FileModel.deleted_at.is_(None),
                    FileModel.is_deleted.is_(False),
                )
            )
        )

    async def list_by_workspace(
        self, workspace_id: WorkspaceId, skip: int = 0, limit: int = 50
    ) -> list[File]:
        models = self.session.scalars(
            select(FileModel)
            .where(
                FileModel.workspace_id == str(workspace_id),
                FileModel.deleted_at.is_(None),
                FileModel.is_deleted.is_(False),
            )
            .offset(skip)
            .limit(limit)
        )
        return [value for model in models if (value := _file(model)) is not None]

    async def delete(self, file_id: FileId, workspace_id: WorkspaceId) -> bool:
        model = self.session.scalar(
            select(FileModel).where(
                FileModel.id == str(file_id),
                FileModel.workspace_id == str(workspace_id),
                FileModel.deleted_at.is_(None),
            )
        )
        if model is None:
            return False
        model.reference_count = max(0, model.reference_count - 1)
        if model.reference_count == 0:
            model.is_deleted, model.deleted_at = True, utc_now()
        return True


def _user(model: UserModel | None) -> User | None:
    return (
        None
        if model is None
        else User(
            UserId(value=model.id),
            model.email,
            model.name,
            model.created_at,
            model.updated_at,
            model.is_active,
        )
    )


def _workspace(model: WorkspaceModel | None) -> Workspace | None:
    return (
        None
        if model is None
        else Workspace(
            WorkspaceId(value=model.id),
            UserId(value=model.user_id),
            model.name,
            model.description,
            model.created_at,
            model.updated_at,
            model.is_active,
        )
    )


def _conversation(model: ConversationModel | None) -> Conversation | None:
    return (
        None
        if model is None
        else Conversation(
            ConversationId(value=model.id),
            WorkspaceId(value=model.workspace_id),
            UserId(value=model.user_id),
            model.title,
            model.description,
            model.created_at,
            model.updated_at,
            model.is_archived,
        )
    )


def _message(model: MessageModel | None) -> Message | None:
    return (
        None
        if model is None
        else Message(
            MessageId(value=model.id),
            ConversationId(value=model.conversation_id),
            MessageRole(model.role),
            MessageType(model.type),
            model.content,
            model.metadata_json,
            model.created_at,
        )
    )


def _task(model: TaskModel | None) -> Task | None:
    return (
        None
        if model is None
        else Task(
            TaskId(value=model.id),
            WorkspaceId(value=model.workspace_id),
            UserId(value=model.user_id),
            ConversationId(value=model.conversation_id),
            TaskStatus(model.status),
            model.input_text,
            model.result,
            model.error_message,
            model.created_at,
            model.updated_at,
            TraceId(value=model.trace_id) if model.trace_id else None,
            model.metadata_json,
        )
    )


def _file(model: FileModel | None) -> File | None:
    return (
        None
        if model is None
        else File(
            FileId(value=model.id),
            WorkspaceId(value=model.workspace_id),
            model.filename,
            model.content_type,
            model.size_bytes,
            model.storage_path,
            model.checksum,
            model.created_at,
            model.updated_at,
            model.is_deleted,
            model.metadata_json,
        )
    )
