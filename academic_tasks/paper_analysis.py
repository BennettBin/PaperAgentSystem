"""Evidence-bound single-paper analysis."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from subagents.paper_reader import PaperCard, PaperEvidence


@dataclass(frozen=True, slots=True)
class EvidencePassage:
    evidence_id: str
    text: str
    page: int
    field_hint: str | None = None


class PaperCardExtractor:
    FIELDS = (
        "title",
        "research_question",
        "methodology",
        "datasets",
        "metrics",
        "results",
        "contributions",
        "limitations",
    )
    PREFIXES = {
        "title": ("title:", "题目："),
        "research_question": ("research question:", "研究问题："),
        "methodology": ("method:", "methodology:", "方法："),
        "datasets": ("dataset:", "datasets:", "数据集："),
        "metrics": ("metric:", "metrics:", "指标："),
        "results": ("result:", "results:", "结果："),
        "contributions": ("contribution:", "contributions:", "贡献："),
        "limitations": ("limitation:", "limitations:", "局限："),
    }

    def extract(self, passages: Iterable[EvidencePassage]) -> PaperCard:
        values: dict[str, list[tuple[str, EvidencePassage]]] = {
            field: [] for field in self.FIELDS
        }
        for passage in passages:
            field = passage.field_hint or self._detect_field(passage.text)
            if field not in values:
                continue
            cleaned = self._clean_value(field, passage.text)
            if cleaned:
                values[field].append((cleaned, passage))
        evidence = [
            PaperEvidence(
                evidence_id=passage.evidence_id,
                field=field,
                quote=passage.text,
                page=passage.page,
            )
            for field, items in values.items()
            for _, passage in items
        ]
        missing = [field for field, items in values.items() if not items]
        return PaperCard(
            title=_first(values["title"]),
            research_question=_first(values["research_question"]),
            methodology=_first(values["methodology"]),
            datasets=_all(values["datasets"]),
            metrics=_all(values["metrics"]),
            results=_all(values["results"]),
            contributions=_all(values["contributions"]),
            limitations=_all(values["limitations"]),
            evidence=evidence,
            missing_fields=missing,
        )

    def _detect_field(self, text: str) -> str | None:
        normalized = text.strip().casefold()
        for field, prefixes in self.PREFIXES.items():
            if any(normalized.startswith(prefix.casefold()) for prefix in prefixes):
                return field
        return None

    def _clean_value(self, field: str, text: str) -> str:
        normalized = text.strip()
        for prefix in self.PREFIXES[field]:
            if normalized.casefold().startswith(prefix.casefold()):
                return normalized[len(prefix) :].strip()
        return normalized


def _first(values: list[tuple[str, EvidencePassage]]) -> str:
    return values[0][0] if values else ""


def _all(values: list[tuple[str, EvidencePassage]]) -> list[str]:
    return list(dict.fromkeys(value for value, _ in values))
