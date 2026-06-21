"""Evidence-preserving multi-paper comparison."""

from __future__ import annotations

import re
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

from subagents.manager import SubAgentBatchResult
from subagents.paper_reader import PaperCard


class ComparisonCell(BaseModel):
    model_config = ConfigDict(extra="forbid")
    file_id: str
    dimension: str
    values: list[str]
    evidence_ids: list[str]
    numbers_verified: bool


class ComparisonConclusion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str
    evidence_ids: list[str]


class ComparisonResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dimensions: list[str]
    matrix: list[ComparisonCell]
    conclusions: list[ComparisonConclusion]
    missing: dict[str, list[str]]


@dataclass(frozen=True, slots=True)
class PaperCardRecord:
    file_id: str
    card: PaperCard


class MultiPaperComparator:
    FIELD_MAP = {
        "methodology": "methodology",
        "datasets": "datasets",
        "metrics": "metrics",
        "results": "results",
        "contributions": "contributions",
        "limitations": "limitations",
    }

    def compare(
        self,
        papers: list[PaperCardRecord],
        dimensions: list[str],
    ) -> ComparisonResult:
        normalized = [dimension.casefold().strip() for dimension in dimensions]
        matrix = []
        missing: dict[str, list[str]] = {}
        for paper in papers:
            missing[paper.file_id] = []
            evidence_by_field = {
                field: [item.evidence_id for item in paper.card.evidence if item.field == field]
                for field in self.FIELD_MAP.values()
            }
            quotes_by_id = {
                item.evidence_id: item.quote for item in paper.card.evidence
            }
            for dimension in normalized:
                field = self.FIELD_MAP.get(dimension, dimension)
                raw = getattr(paper.card, field, None)
                values = [raw] if isinstance(raw, str) and raw else list(raw or [])
                evidence_ids = evidence_by_field.get(field, [])
                if not values:
                    missing[paper.file_id].append(dimension)
                matrix.append(
                    ComparisonCell(
                        file_id=paper.file_id,
                        dimension=dimension,
                        values=values,
                        evidence_ids=evidence_ids,
                        numbers_verified=self._numbers_verified(
                            values,
                            [quotes_by_id[item] for item in evidence_ids if item in quotes_by_id],
                        ),
                    )
                )
        conclusions = self._conclusions(matrix)
        return ComparisonResult(
            dimensions=normalized,
            matrix=matrix,
            conclusions=conclusions,
            missing={key: value for key, value in missing.items() if value},
        )

    def compare_batch(
        self,
        batch: SubAgentBatchResult,
        dimensions: list[str],
    ) -> ComparisonResult:
        papers = [
            PaperCardRecord(
                file_id=item.file_id,
                card=PaperCard.model_validate((item.result or {})["card"]),
            )
            for item in batch.completed
            if item.result and "card" in item.result
        ]
        return self.compare(papers, dimensions)

    @staticmethod
    def _numbers_verified(values: list[str], evidence: list[str]) -> bool:
        value_numbers = set(_numbers(" ".join(values)))
        evidence_numbers = set(_numbers(" ".join(evidence)))
        return value_numbers <= evidence_numbers

    @staticmethod
    def _conclusions(matrix: list[ComparisonCell]) -> list[ComparisonConclusion]:
        conclusions = []
        dimensions = list(dict.fromkeys(cell.dimension for cell in matrix))
        for dimension in dimensions:
            cells = [cell for cell in matrix if cell.dimension == dimension and cell.values]
            if not cells or any(not cell.evidence_ids or not cell.numbers_verified for cell in cells):
                continue
            summary = "; ".join(
                f"{cell.file_id}: {', '.join(cell.values)}" for cell in cells
            )
            conclusions.append(
                ComparisonConclusion(
                    text=f"{dimension}: {summary}",
                    evidence_ids=list(
                        dict.fromkeys(
                            evidence_id
                            for cell in cells
                            for evidence_id in cell.evidence_ids
                        )
                    ),
                )
            )
        return conclusions


def _numbers(text: str) -> list[str]:
    return re.findall(r"(?<!\w)\d+(?:\.\d+)?%?", text)
