import math
import re
from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from backend.core.domain.ids import ConversationId, WorkspaceId
from backend.core.ports.llm_client import EmbeddingClient
from backend.infrastructure.postgres.models import (
    MemorySegmentModel,
    MessageFileModel,
    MessageModel,
    utc_now,
)
from backend.memory.summarizer import (
    StructuredMemorySummarizer,
    StructuredMemorySummary,
)


@dataclass(frozen=True)
class MemoryRecall:
    segment_id: str
    summary: str
    source_messages: list[dict[str, str]]
    score: float


class ShortTermMemoryService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        embeddings: EmbeddingClient,
        message_threshold: int = 8,
        token_threshold: int = 1200,
        *,
        summarizer: StructuredMemorySummarizer | None = None,
        recent_window: int = 12,
        segment_size: int = 12,
    ) -> None:
        self.session_factory = session_factory
        self.embeddings = embeddings
        self.message_threshold = message_threshold
        self.token_threshold = token_threshold
        self.summarizer = summarizer or StructuredMemorySummarizer(None)
        self.recent_window = recent_window
        self.segment_size = segment_size

    def recent_messages(
        self, workspace_id: WorkspaceId, conversation_id: ConversationId, limit: int = 12
    ) -> list[dict[str, str]]:
        with self.session_factory() as session:
            models = list(
                session.scalars(
                    select(MessageModel)
                    .where(
                        MessageModel.workspace_id == str(workspace_id),
                        MessageModel.conversation_id == str(conversation_id),
                        MessageModel.deleted_at.is_(None),
                    )
                    .order_by(MessageModel.created_at.desc(), MessageModel.id.desc())
                    .limit(limit)
                )
            )
        return [
            {"message_id": model.id, "role": model.role, "content": model.content}
            for model in reversed(models)
        ]

    async def summarize_if_needed(
        self, workspace_id: WorkspaceId, conversation_id: ConversationId
    ) -> str | None:
        with self.session_factory() as session:
            messages = list(
                session.scalars(
                    select(MessageModel)
                    .where(
                        MessageModel.workspace_id == str(workspace_id),
                        MessageModel.conversation_id == str(conversation_id),
                        MessageModel.deleted_at.is_(None),
                    )
                    .order_by(MessageModel.created_at)
                )
            )
            if len(messages) <= self.recent_window:
                return None
            eligible = messages[: -self.recent_window]
            existing_segments = list(
                session.scalars(
                select(MemorySegmentModel).where(
                    MemorySegmentModel.workspace_id == str(workspace_id),
                    MemorySegmentModel.conversation_id == str(conversation_id),
                    MemorySegmentModel.invalidated_at.is_(None),
                )
                .order_by(MemorySegmentModel.source_start_at)
                )
            )
            recent_ids = {message.id for message in messages[-self.recent_window :]}
            seen_ids: set[str] = set()
            active_segments: list[MemorySegmentModel] = []
            for segment in existing_segments:
                structured = StructuredMemorySummary.from_storage_text(segment.summary)
                segment_ids = set(segment.source_message_ids)
                if (
                    structured is None
                    or segment_ids & recent_ids
                    or segment_ids & seen_ids
                    or len(segment.source_message_ids) > self.segment_size
                ):
                    segment.invalidated_at = utc_now()
                    continue
                seen_ids.update(segment_ids)
                active_segments.append(segment)

            eligible_by_id = {message.id: message for message in eligible}
            assigned_ids = {
                message_id
                for segment in active_segments
                for message_id in segment.source_message_ids
                if message_id in eligible_by_id
            }
            unassigned = [
                message for message in eligible if message.id not in assigned_ids
            ]
            last_changed_id: str | None = None
            if active_segments and unassigned:
                tail = active_segments[-1]
                capacity = self.segment_size - len(tail.source_message_ids)
                appendable = [
                    message
                    for message in unassigned
                    if message.created_at >= tail.source_end_at
                ][:capacity]
                if appendable:
                    await self._update_segment(session, tail, appendable)
                    appended_ids = {message.id for message in appendable}
                    unassigned = [
                        message for message in unassigned if message.id not in appended_ids
                    ]
                    last_changed_id = tail.id

            for start in range(0, len(unassigned), self.segment_size):
                window = unassigned[start : start + self.segment_size]
                if not window:
                    continue
                segment = await self._new_segment(
                    session,
                    str(workspace_id),
                    str(conversation_id),
                    window,
                )
                active_segments.append(segment)
                last_changed_id = segment.id
            session.commit()
            return last_changed_id or (active_segments[-1].id if active_segments else None)

    async def _new_segment(
        self,
        session: Session,
        workspace_id: str,
        conversation_id: str,
        messages: list[MessageModel],
    ) -> MemorySegmentModel:
        source_ids = [message.id for message in messages]
        inputs, file_ids = _summary_inputs(session, messages)
        structured = await self.summarizer.summarize(
            inputs,
            source_message_ids=source_ids,
            referenced_files=file_ids,
        )
        summary = structured.to_storage_text()
        segment = MemorySegmentModel(
            id=uuid4().hex,
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            summary=summary,
            embedding=await self.embeddings.embed(summary),
            embedding_fingerprint=_embedding_fingerprint(self.embeddings),
            source_message_ids=source_ids,
            source_start_at=messages[0].created_at,
            source_end_at=messages[-1].created_at,
        )
        session.add(segment)
        return segment

    async def _update_segment(
        self,
        session: Session,
        segment: MemorySegmentModel,
        messages: list[MessageModel],
    ) -> None:
        source_ids = [*segment.source_message_ids, *(message.id for message in messages)]
        inputs, file_ids = _summary_inputs(session, messages)
        structured = await self.summarizer.summarize(
            inputs,
            previous_summary=segment.summary,
            source_message_ids=source_ids,
            referenced_files=file_ids,
        )
        summary = structured.to_storage_text()
        segment.summary = summary
        segment.embedding = await self.embeddings.embed(summary)
        segment.embedding_fingerprint = _embedding_fingerprint(self.embeddings)
        segment.source_message_ids = source_ids
        segment.source_end_at = messages[-1].created_at

    async def recall(
        self,
        workspace_id: WorkspaceId,
        conversation_id: ConversationId,
        query: str,
        top_k: int = 5,
    ) -> list[MemoryRecall]:
        query_terms = set(_terms(query))
        query_embedding = await self.embeddings.embed(query)
        with self.session_factory() as session:
            segments = session.scalars(
                select(MemorySegmentModel).where(
                    MemorySegmentModel.workspace_id == str(workspace_id),
                    MemorySegmentModel.conversation_id == str(conversation_id),
                    MemorySegmentModel.invalidated_at.is_(None),
                )
            )
            ranked = []
            for segment in segments:
                lexical = len(query_terms & set(_terms(segment.summary))) / max(
                    1, len(query_terms)
                )
                vector_score = (
                    _cosine(query_embedding, segment.embedding)
                    if segment.embedding_fingerprint
                    == _embedding_fingerprint(self.embeddings)
                    else 0.0
                )
                score = lexical * 2 + vector_score
                ranked.append((score, segment))
            selected = sorted(ranked, key=lambda item: -item[0])[:top_k]
            results = []
            for score, segment in selected:
                messages = list(
                    session.scalars(
                        select(MessageModel)
                        .where(
                            MessageModel.id.in_(segment.source_message_ids),
                            MessageModel.deleted_at.is_(None),
                        )
                        .order_by(MessageModel.created_at)
                    )
                )
                results.append(
                    MemoryRecall(
                        segment_id=segment.id,
                        summary=segment.summary,
                        source_messages=[
                            {
                                "message_id": message.id,
                                "role": message.role,
                                "content": message.content,
                            }
                            for message in messages
                        ],
                        score=score,
                    )
                )
            return results

    def invalidate_for_message(self, message_id: str, workspace_id: WorkspaceId) -> int:
        with self.session_factory() as session:
            segments = session.scalars(
                select(MemorySegmentModel).where(
                    MemorySegmentModel.workspace_id == str(workspace_id),
                    MemorySegmentModel.invalidated_at.is_(None),
                )
            )
            count = 0
            for segment in segments:
                if message_id in segment.source_message_ids:
                    segment.invalidated_at = utc_now()
                    count += 1
            session.commit()
            return count


def _terms(text: str) -> list[str]:
    return re.findall(r"[\w\u4e00-\u9fff]+", text.lower())


def _cosine(left: list[float], right: list[float]) -> float:
    size = max(len(left), len(right))
    if size == 0:
        return 0
    a, b = left + [0.0] * (size - len(left)), right + [0.0] * (size - len(right))
    denominator = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(x * x for x in b))
    return 0 if denominator == 0 else sum(x * y for x, y in zip(a, b)) / denominator


def _embedding_fingerprint(embeddings: EmbeddingClient) -> str:
    profile = getattr(embeddings, "profile", None)
    return profile.fingerprint if profile is not None else ""


def _summary_inputs(
    session: Session, messages: list[MessageModel]
) -> tuple[list[dict[str, object]], list[str]]:
    message_ids = [message.id for message in messages]
    links = list(
        session.execute(
            select(MessageFileModel.message_id, MessageFileModel.file_id).where(
                MessageFileModel.message_id.in_(message_ids),
                MessageFileModel.deleted_at.is_(None),
            )
        )
    )
    files_by_message: dict[str, list[str]] = {}
    for message_id, file_id in links:
        files_by_message.setdefault(message_id, []).append(file_id)
    return (
        [
            {
                "message_id": message.id,
                "role": message.role,
                "content": message.content,
                "file_ids": files_by_message.get(message.id, []),
            }
            for message in messages
        ],
        list(dict.fromkeys(file_id for _, file_id in links)),
    )
