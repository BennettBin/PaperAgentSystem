from datetime import UTC, datetime

from core.domain.conversation import Conversation, Message
from core.domain.ids import ConversationId, FileId, MessageId, UserId, WorkspaceId
from core.errors import NotFoundError
from infrastructure.postgres.repositories import (
    SqlAlchemyConversationRepository,
    SqlAlchemyMessageRepository,
)


class ConversationService:
    def __init__(
        self,
        conversations: SqlAlchemyConversationRepository,
        messages: SqlAlchemyMessageRepository,
    ) -> None:
        self.conversations = conversations
        self.messages = messages

    async def create(
        self, workspace_id: WorkspaceId, user_id: UserId, title: str
    ) -> Conversation:
        conversation = Conversation.create(workspace_id, user_id, title)
        await self.conversations.save(conversation)
        return conversation

    async def rename(
        self, conversation_id: ConversationId, workspace_id: WorkspaceId, title: str
    ) -> Conversation:
        conversation = await self.conversations.find_by_id(conversation_id, workspace_id)
        if conversation is None:
            raise NotFoundError("conversation", str(conversation_id))
        conversation.title = title
        conversation.updated_at = datetime.now(UTC)
        await self.conversations.save(conversation)
        return conversation

    async def search(
        self,
        workspace_id: WorkspaceId,
        query: str = "",
        skip: int = 0,
        limit: int = 50,
    ) -> list[Conversation]:
        return await self.conversations.search(workspace_id, query, skip, limit)

    async def add_message(
        self,
        conversation_id: ConversationId,
        workspace_id: WorkspaceId,
        content: str,
        *,
        assistant: bool = False,
        file_ids: list[FileId] | None = None,
    ) -> Message:
        conversation = await self.conversations.find_by_id(conversation_id, workspace_id)
        if conversation is None:
            raise NotFoundError("conversation", str(conversation_id))
        message = (
            Message.create_assistant_message(conversation_id, content)
            if assistant
            else Message.create_user_message(conversation_id, content)
        )
        await self.messages.save(message)
        for file_id in file_ids or []:
            await self.messages.attach_file(message.id, file_id, workspace_id)
        return message

    async def delete_message(
        self, message_id: MessageId, workspace_id: WorkspaceId
    ) -> bool:
        return await self.messages.delete(message_id, workspace_id)

    async def delete_message_range(
        self,
        conversation_id: ConversationId,
        workspace_id: WorkspaceId,
        start: datetime,
        end: datetime,
    ) -> int:
        return await self.messages.delete_range(
            conversation_id, workspace_id, start, end
        )

    async def delete_conversation(
        self, conversation_id: ConversationId, workspace_id: WorkspaceId
    ) -> bool:
        return await self.conversations.delete(conversation_id, workspace_id)
