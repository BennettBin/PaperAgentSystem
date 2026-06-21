import math
import re
from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from core.domain.ids import ConversationId, WorkspaceId
from core.ports.llm_client import EmbeddingClient
from infrastructure.postgres.models import MemorySegmentModel, MessageModel, utc_now


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
    ) -> None:
        self.session_factory = session_factory
        self.embeddings = embeddings
        self.message_threshold = message_threshold
        self.token_threshold = token_threshold

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
                    .order_by(MessageModel.created_at.desc())
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
            token_count = sum(len(_terms(message.content)) for message in messages)
            if len(messages) < self.message_threshold and token_count < self.token_threshold:
                return None
            source_ids = [message.id for message in messages]
            existing = session.scalar(
                select(MemorySegmentModel).where(
                    MemorySegmentModel.workspace_id == str(workspace_id),
                    MemorySegmentModel.conversation_id == str(conversation_id),
                    MemorySegmentModel.source_message_ids == source_ids,
                    MemorySegmentModel.invalidated_at.is_(None),
                )
            )
            if existing is not None:
                return existing.id
            summary = " | ".join(
                f"{message.role}: {' '.join(message.content.split())}" for message in messages
            )
            embedding = await self.embeddings.embed(summary)
            segment = MemorySegmentModel(
                id=uuid4().hex,
                workspace_id=str(workspace_id),
                conversation_id=str(conversation_id),
                summary=summary,
                embedding=embedding,
                source_message_ids=source_ids,
                source_start_at=messages[0].created_at,
                source_end_at=messages[-1].created_at,
            )
            session.add(segment)
            session.commit()
            return segment.id

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
                score = lexical * 2 + _cosine(query_embedding, segment.embedding)
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
