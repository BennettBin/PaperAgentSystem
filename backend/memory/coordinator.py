"""Application-level orchestration for durable conversation memory."""

from __future__ import annotations

from typing import Any

from backend.core.domain.ids import ConversationId, WorkspaceId
from backend.memory.long_term import LongTermMemoryService
from backend.memory.short_term import ShortTermMemoryService


class ConversationMemoryCoordinator:
    """Build both memory levels from the same persisted conversation snapshot."""

    def __init__(
        self,
        short_term: ShortTermMemoryService,
        long_term: LongTermMemoryService,
    ) -> None:
        self._short_term = short_term
        self._long_term = long_term

    async def summarize(
        self,
        workspace_id: str,
        conversation_id: str,
    ) -> dict[str, Any]:
        short_term_segment_id = await self._short_term.summarize_if_needed(
            WorkspaceId(value=workspace_id),
            ConversationId(value=conversation_id),
        )
        long_term_summary_id = await self._long_term.summarize_conversation(
            workspace_id,
            conversation_id,
        )
        return {
            "status": (
                "completed"
                if short_term_segment_id or long_term_summary_id
                else "skipped"
            ),
            "conversation_id": conversation_id,
            "short_term_segment_id": short_term_segment_id,
            "long_term_summary_id": long_term_summary_id,
        }
