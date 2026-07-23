"""Inter-annotator agreement contracts for evaluation dataset releases."""

from __future__ import annotations

from collections import Counter

from pydantic import BaseModel, ConfigDict, Field


class AnnotationPair(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    annotator_a_label: str = Field(min_length=1)
    annotator_b_label: str = Field(min_length=1)
    annotator_a_id: str | None = None
    annotator_b_id: str | None = None
    adjudication: str | None = None


def cohen_kappa(pairs: list[AnnotationPair]) -> float:
    if not pairs:
        raise ValueError("Cohen's kappa requires at least one annotation pair")
    total = len(pairs)
    observed = sum(
        pair.annotator_a_label == pair.annotator_b_label for pair in pairs
    ) / total
    counts_a = Counter(pair.annotator_a_label for pair in pairs)
    counts_b = Counter(pair.annotator_b_label for pair in pairs)
    labels = set(counts_a) | set(counts_b)
    expected = sum((counts_a[label] / total) * (counts_b[label] / total) for label in labels)
    if expected == 1.0:
        return 1.0 if observed == 1.0 else 0.0
    return (observed - expected) / (1.0 - expected)
