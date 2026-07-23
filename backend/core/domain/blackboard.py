"""Versioned, source-traceable entities for the shared Evidence Blackboard."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class BlackboardEntryKind(StrEnum):
    RESEARCH_QUESTION = "research_question"
    PAPER_CARD = "paper_card"
    CLAIM = "claim"
    EVIDENCE = "evidence"
    CONFLICT = "conflict"
    GAP = "gap"
    DRAFT_SECTION = "draft_section"
    VERIFICATION_RESULT = "verification_result"


class EvidenceSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_id: str | None = None
    message_id: str | None = None
    citation_id: str | None = None
    page_number: int | None = Field(default=None, ge=1)
    inferred: bool = False


class BlackboardEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    entry_id: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    kind: BlackboardEntryKind
    producer_role: str = Field(min_length=1)
    version: int = Field(default=1, ge=1)
    confidence: float = Field(ge=0.0, le=1.0)
    payload: dict[str, Any]
    source: EvidenceSource
    invalidated_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def evidence_has_provenance(self) -> Self:
        if self.kind in {BlackboardEntryKind.CLAIM, BlackboardEntryKind.EVIDENCE}:
            has_pdf_location = bool(self.source.file_id and self.source.page_number)
            if not has_pdf_location and not self.source.inferred:
                raise ValueError("Claim/Evidence requires a PDF page or inferred=true")
        return self

    def next_version(self, *, payload: dict[str, Any]) -> Self:
        return self.model_copy(
            update={
                "version": self.version + 1,
                "payload": payload,
                "updated_at": datetime.now(UTC),
                "invalidated_at": None,
            }
        )

    def invalidate(self) -> Self:
        now = datetime.now(UTC)
        return self.model_copy(
            update={"version": self.version + 1, "invalidated_at": now, "updated_at": now}
        )


class BlackboardEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str = Field(min_length=1)
    event_type: Literal["created", "updated", "invalidated"]
    entry: BlackboardEntry
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
