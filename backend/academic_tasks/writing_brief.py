"""Writing Brief and Evidence Map construction."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class StatementKind(str, Enum):
    FACT = "fact"
    OPINION = "opinion"
    INFERENCE = "inference"


class SourceMaterial(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    kind: StatementKind
    evidence_ids: list[str] = Field(default_factory=list)


class EvidenceMapItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    statement_id: str
    text: str
    kind: StatementKind
    source_ids: list[str]
    evidence_ids: list[str]
    allowed_as_fact: bool


class WritingBrief(BaseModel):
    model_config = ConfigDict(extra="forbid")
    section_type: str
    target_language: str
    target_length: int = Field(gt=0)
    style: str
    user_points: list[str]
    immutable_items: list[str]
    missing_information: list[str]
    evidence_map: list[EvidenceMapItem]


class WritingBriefBuilder:
    def build(
        self,
        *,
        section_type: str,
        target_language: str,
        target_length: int,
        style: str,
        user_points: list[str],
        materials: list[SourceMaterial],
        immutable_items: list[str],
    ) -> WritingBrief:
        normalized_points = list(dict.fromkeys(point.strip() for point in user_points if point.strip()))
        evidence_map = [
            EvidenceMapItem(
                statement_id=f"statement-{index}",
                text=material.text,
                kind=material.kind,
                source_ids=[material.source_id],
                evidence_ids=material.evidence_ids,
                allowed_as_fact=(
                    material.kind is StatementKind.FACT
                    and bool(material.source_id)
                    and bool(material.evidence_ids)
                ),
            )
            for index, material in enumerate(materials, start=1)
        ]
        missing = []
        if not normalized_points:
            missing.append("user_points")
        if not any(item.allowed_as_fact for item in evidence_map):
            missing.append("supported_facts")
        return WritingBrief(
            section_type=section_type,
            target_language=target_language,
            target_length=target_length,
            style=style,
            user_points=normalized_points,
            immutable_items=list(dict.fromkeys(immutable_items)),
            missing_information=missing,
            evidence_map=evidence_map,
        )
