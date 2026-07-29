"""Small-model structured summarization for conversation memory."""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from backend.core.ports.llm_client import LLMClient

LOGGER = logging.getLogger(__name__)


class StructuredMemorySummary(BaseModel):
    """Search-oriented memory metadata; original messages remain the source of truth."""

    topics: list[str] = Field(default_factory=list)
    user_goals: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    referenced_files: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    source_message_ids: list[str] = Field(default_factory=list)

    def to_storage_text(self) -> str:
        return self.model_dump_json()

    @classmethod
    def from_storage_text(cls, value: str | None) -> StructuredMemorySummary | None:
        if not value:
            return None
        try:
            return cls.model_validate_json(value)
        except ValidationError:
            return None


class StructuredMemorySummarizer:
    """Generate bounded structured memory with the small model and a safe fallback."""

    def __init__(self, llm: LLMClient | None) -> None:
        self._llm = llm

    async def summarize(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        previous_summary: str | None = None,
        source_message_ids: Sequence[str],
        referenced_files: Sequence[str] = (),
    ) -> StructuredMemorySummary:
        authoritative_ids = list(dict.fromkeys(str(item) for item in source_message_ids))
        authoritative_files = list(dict.fromkeys(str(item) for item in referenced_files))
        fallback = self._fallback(
            messages,
            previous_summary=previous_summary,
            source_message_ids=authoritative_ids,
            referenced_files=authoritative_files,
        )
        if self._llm is None:
            return fallback
        prompt = _summary_prompt(messages, previous_summary)
        try:
            raw = await self._llm.generate_with_schema(
                prompt,
                system_prompt=(
                    "你是会话记忆摘要器。只提取输入中明确出现的信息，不补充事实；"
                    "输出完整 JSON，字段必须符合给定 Schema。"
                ),
                response_schema=StructuredMemorySummary.model_json_schema(),
                max_tokens=1200,
                temperature=0.0,
            )
            result = StructuredMemorySummary.model_validate_json(raw)
        except Exception:
            LOGGER.warning(
                "Small-model memory summarization failed; using deterministic fallback",
                exc_info=True,
            )
            return fallback
        result.source_message_ids = authoritative_ids
        result.referenced_files = list(
            dict.fromkeys([*result.referenced_files, *authoritative_files])
        )
        return result

    @staticmethod
    def _fallback(
        messages: Sequence[dict[str, Any]],
        *,
        previous_summary: str | None,
        source_message_ids: list[str],
        referenced_files: list[str],
    ) -> StructuredMemorySummary:
        previous = StructuredMemorySummary.from_storage_text(previous_summary)
        if previous is None:
            previous = StructuredMemorySummary()
        user_lines = [
            " ".join(str(item.get("content", "")).split())[:240]
            for item in messages
            if item.get("role") == "user" and str(item.get("content", "")).strip()
        ]
        assistant_lines = [
            " ".join(str(item.get("content", "")).split())[:240]
            for item in messages
            if item.get("role") != "user" and str(item.get("content", "")).strip()
        ]
        return StructuredMemorySummary(
            topics=_unique([*previous.topics, *user_lines[-3:]]),
            user_goals=_unique([*previous.user_goals, *user_lines[-3:]]),
            decisions=_unique([*previous.decisions, *assistant_lines[-3:]]),
            referenced_files=_unique(
                [*previous.referenced_files, *referenced_files]
            ),
            open_questions=list(previous.open_questions),
            source_message_ids=source_message_ids,
        )


def _summary_prompt(
    messages: Sequence[dict[str, Any]], previous_summary: str | None
) -> str:
    payload = {
        "previous_summary": previous_summary,
        "new_messages": [
            {
                "message_id": item.get("message_id"),
                "role": item.get("role"),
                "content": item.get("content"),
                "file_ids": item.get("file_ids", []),
            }
            for item in messages
        ],
    }
    return (
        "基于 previous_summary 和 new_messages 生成更新后的结构化记忆。"
        "保留仍然有效的主题、目标和决定；已解决的问题不要继续列入 open_questions。"
        "文件只记录 file_id。source_message_ids 由系统校正。\n"
        + json.dumps(payload, ensure_ascii=False)
    )


def _unique(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
