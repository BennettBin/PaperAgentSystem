"""JSONL loading and leakage/privacy validation."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from pydantic import ValidationError

from training.contracts import DatasetValidation, TrainingSample


class DatasetValidationError(ValueError):
    pass


def load_samples(path: Path) -> list[TrainingSample]:
    samples: list[TrainingSample] = []
    seen_ids: set[str] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            sample = TrainingSample.model_validate(json.loads(line))
        except (json.JSONDecodeError, ValidationError) as exc:
            raise DatasetValidationError(f"invalid sample at line {line_number}: {exc}") from exc
        if sample.sample_id in seen_ids:
            raise DatasetValidationError(f"duplicate sample_id: {sample.sample_id}")
        seen_ids.add(sample.sample_id)
        samples.append(sample)
    if not samples:
        raise DatasetValidationError("dataset is empty")
    return samples


def validate_dataset(path: Path) -> DatasetValidation:
    samples = load_samples(path)
    paper_splits: dict[str, set[str]] = defaultdict(set)
    conversation_splits: dict[str, set[str]] = defaultdict(set)
    for sample in samples:
        for paper_id in sample.paper_ids:
            paper_splits[paper_id].add(sample.dataset_split.value)
        for conversation_id in sample.conversation_ids:
            conversation_splits[conversation_id].add(sample.dataset_split.value)

    leaked_papers = sorted(key for key, splits in paper_splits.items() if len(splits) > 1)
    leaked_conversations = sorted(
        key for key, splits in conversation_splits.items() if len(splits) > 1
    )
    if leaked_papers or leaked_conversations:
        raise DatasetValidationError(
            "paper/conversation split leakage: "
            f"papers={leaked_papers}, conversations={leaked_conversations}"
        )

    return DatasetValidation(
        sample_count=len(samples),
        split_counts=dict(Counter(item.dataset_split.value for item in samples)),
        learning_method_counts=dict(Counter(item.learning_method for item in samples)),
        privacy_counts=dict(Counter(item.privacy.value for item in samples)),
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    )
