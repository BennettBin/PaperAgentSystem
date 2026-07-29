import math
import re
from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from backend.core.ports.llm_client import EmbeddingClient
from backend.infrastructure.postgres.models import (
    ConversationModel,
    ConversationSummaryModel,
    MemoryPreferenceModel,
    MessageFileModel,
    MessageModel,
    WorkspaceEntryModel,
    WorkspaceSearchModel,
    utc_now,
)
from backend.memory.summarizer import StructuredMemorySummarizer


@dataclass(frozen=True)
class LongTermRecall:
    kind: str
    id: str
    conversation_id: str | None
    text: str
    score: float
    source_ids: list[str]


class LongTermMemoryService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        embeddings: EmbeddingClient,
        *,
        summarizer: StructuredMemorySummarizer | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.embeddings = embeddings
        self.summarizer = summarizer or StructuredMemorySummarizer(None)

    async def summarize_conversation(
        self, workspace_id: str, conversation_id: str
    ) -> str | None:
        with self.session_factory() as session:
            conversation = session.scalar(
                select(ConversationModel).where(
                    ConversationModel.id == conversation_id,
                    ConversationModel.workspace_id == workspace_id,
                    ConversationModel.deleted_at.is_(None),
                )
            )
            if conversation is None:
                return None
            model = session.get(ConversationSummaryModel, conversation_id)
            covered_ids = set(model.source_message_ids if model is not None else [])
            messages = list(
                session.scalars(
                    select(MessageModel)
                    .where(
                        MessageModel.workspace_id == workspace_id,
                        MessageModel.conversation_id == conversation_id,
                        MessageModel.deleted_at.is_(None),
                    )
                    .order_by(MessageModel.created_at, MessageModel.id)
                )
            )
            if not messages:
                return None
            new_messages = [message for message in messages if message.id not in covered_ids]
            if not new_messages and model is not None:
                return conversation_id
            message_ids = [message.id for message in messages]
            new_ids = [message.id for message in new_messages]
            links = list(
                session.execute(
                    select(MessageFileModel.message_id, MessageFileModel.file_id).where(
                        MessageFileModel.message_id.in_(new_ids),
                        MessageFileModel.deleted_at.is_(None),
                    )
                )
            ) if new_ids else []
            files_by_message: dict[str, list[str]] = {}
            for message_id, file_id in links:
                files_by_message.setdefault(message_id, []).append(file_id)
            structured = await self.summarizer.summarize(
                [
                    {
                        "message_id": message.id,
                        "role": message.role,
                        "content": message.content,
                        "file_ids": files_by_message.get(message.id, []),
                    }
                    for message in new_messages
                ],
                previous_summary=model.summary if model is not None else None,
                source_message_ids=message_ids,
                referenced_files=[file_id for _, file_id in links],
            )
            summary = structured.to_storage_text()
            embedding = await self.embeddings.embed(summary)
            if model is None:
                model = ConversationSummaryModel(
                    conversation_id=conversation_id,
                    workspace_id=workspace_id,
                    summary=summary,
                    embedding=embedding,
                    embedding_fingerprint=_embedding_fingerprint(self.embeddings),
                    source_message_ids=message_ids,
                )
            else:
                model.summary = summary
                model.embedding = embedding
                model.embedding_fingerprint = _embedding_fingerprint(self.embeddings)
                model.source_message_ids = message_ids
                model.invalidated_at = None
            session.add(model)
            session.commit()
            return conversation_id

    def save_preference(
        self,
        workspace_id: str,
        user_id: str,
        key: str,
        value: object,
        category: str,
        *,
        explicit: bool,
    ) -> str:
        if not explicit:
            raise ValueError("Long-term preferences require explicit user consent")
        with self.session_factory() as session:
            model = session.scalar(
                select(MemoryPreferenceModel).where(
                    MemoryPreferenceModel.workspace_id == workspace_id,
                    MemoryPreferenceModel.user_id == user_id,
                    MemoryPreferenceModel.key == key,
                    MemoryPreferenceModel.deleted_at.is_(None),
                )
            )
            if model is None:
                model = MemoryPreferenceModel(
                    id=uuid4().hex,
                    workspace_id=workspace_id,
                    user_id=user_id,
                    key=key,
                    value=value,
                    category=category,
                    explicitly_saved=True,
                )
            else:
                model.value, model.category = value, category
            session.add(model)
            session.commit()
            return model.id

    async def search(
        self,
        workspace_id: str,
        query: str,
        top_k: int = 5,
        *,
        exclude_conversation_id: str | None = None,
    ) -> list[LongTermRecall]:
        terms = set(_terms(query))
        embedding = await self.embeddings.embed(query)
        candidates: list[LongTermRecall] = []
        with self.session_factory() as session:
            summary_query = select(ConversationSummaryModel).where(
                ConversationSummaryModel.workspace_id == workspace_id,
                ConversationSummaryModel.invalidated_at.is_(None),
                ConversationSummaryModel.deleted_at.is_(None),
            )
            if exclude_conversation_id:
                summary_query = summary_query.where(
                    ConversationSummaryModel.conversation_id
                    != exclude_conversation_id
                )
            summaries = session.scalars(summary_query)
            for conversation_summary in summaries:
                score = _score(
                    terms,
                    embedding,
                    conversation_summary.summary,
                    conversation_summary.embedding,
                    vector_compatible=(
                        conversation_summary.embedding_fingerprint
                        == _embedding_fingerprint(self.embeddings)
                    ),
                )
                candidates.append(
                    LongTermRecall(
                        "conversation",
                        conversation_summary.conversation_id,
                        conversation_summary.conversation_id,
                        conversation_summary.summary,
                        score,
                        conversation_summary.source_message_ids,
                    )
                )
            files = session.scalars(
                select(WorkspaceSearchModel)
                .join(
                    WorkspaceEntryModel,
                    WorkspaceEntryModel.id == WorkspaceSearchModel.entry_id,
                )
                .where(
                    WorkspaceSearchModel.workspace_id == workspace_id,
                    WorkspaceEntryModel.deleted_at.is_(None),
                )
            )
            for workspace_file in files:
                text = (
                    f"{workspace_file.filename} {workspace_file.summary} "
                    f"{workspace_file.extracted_text}"
                )
                score = _score(
                    terms,
                    embedding,
                    text,
                    workspace_file.embedding,
                    vector_compatible=(
                        workspace_file.embedding_fingerprint
                        == _embedding_fingerprint(self.embeddings)
                    ),
                )
                candidates.append(
                    LongTermRecall(
                        "workspace_entry",
                        workspace_file.entry_id,
                        workspace_file.conversation_id,
                        text,
                        score,
                        [workspace_file.source_id] if workspace_file.source_id else [],
                    )
                )
        return sorted(candidates, key=lambda item: (-item.score, item.id))[:top_k]

    def list_preferences(self, workspace_id: str, user_id: str) -> dict[str, object]:
        with self.session_factory() as session:
            models = session.scalars(
                select(MemoryPreferenceModel).where(
                    MemoryPreferenceModel.workspace_id == workspace_id,
                    MemoryPreferenceModel.user_id == user_id,
                    MemoryPreferenceModel.explicitly_saved.is_(True),
                    MemoryPreferenceModel.deleted_at.is_(None),
                )
            )
            return {model.key: model.value for model in models}

    def forget_conversation(self, workspace_id: str, conversation_id: str) -> None:
        with self.session_factory() as session:
            conversation = session.scalar(
                select(ConversationModel).where(
                    ConversationModel.id == conversation_id,
                    ConversationModel.workspace_id == workspace_id,
                )
            )
            if conversation is not None:
                conversation.deleted_at = utc_now()
            summary = session.get(ConversationSummaryModel, conversation_id)
            if summary is not None:
                session.delete(summary)
            entries = session.scalars(
                select(WorkspaceEntryModel).where(
                    WorkspaceEntryModel.workspace_id == workspace_id,
                    WorkspaceEntryModel.conversation_id == conversation_id,
                )
            )
            for entry in entries:
                index = session.get(WorkspaceSearchModel, entry.id)
                if index is not None:
                    session.delete(index)
                entry.deleted_at = utc_now()
            session.commit()

    def forget_preference(self, preference_id: str, workspace_id: str) -> bool:
        with self.session_factory() as session:
            model = session.scalar(
                select(MemoryPreferenceModel).where(
                    MemoryPreferenceModel.id == preference_id,
                    MemoryPreferenceModel.workspace_id == workspace_id,
                    MemoryPreferenceModel.deleted_at.is_(None),
                )
            )
            if model is None:
                return False
            model.deleted_at = utc_now()
            session.commit()
            return True


def _terms(text: str) -> list[str]:
    return re.findall(r"[\w\u4e00-\u9fff]+", text.lower())


def _score(
    query_terms: set[str],
    query_embedding: list[float],
    text: str,
    embedding: list[float],
    *,
    vector_compatible: bool,
) -> float:
    lexical = len(query_terms & set(_terms(text))) / max(1, len(query_terms))
    vector_score = _cosine(query_embedding, embedding) if vector_compatible else 0.0
    return lexical * 2 + vector_score


def _embedding_fingerprint(embeddings: EmbeddingClient) -> str:
    profile = getattr(embeddings, "profile", None)
    return profile.fingerprint if profile is not None else ""


def _cosine(left: list[float], right: list[float]) -> float:
    size = max(len(left), len(right))
    if size == 0:
        return 0
    a, b = left + [0.0] * (size - len(left)), right + [0.0] * (size - len(right))
    denominator = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(x * x for x in b))
    return 0 if denominator == 0 else sum(x * y for x, y in zip(a, b)) / denominator
