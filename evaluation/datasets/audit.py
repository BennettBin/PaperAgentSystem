"""Dataset loading, provenance/privacy validation and split-leakage auditing."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from pathlib import Path

from pydantic import ValidationError

from evaluation.datasets.schema import DatasetBuildManifest, EvaluationCase, SplitLeakage


class DatasetAuditError(ValueError):
    """Raised when a dataset violates a fail-closed evaluation-data gate."""


def load_cases(path: Path) -> list[EvaluationCase]:
    cases: list[EvaluationCase] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            cases.append(EvaluationCase.model_validate_json(line))
        except (ValidationError, ValueError) as exc:
            raise DatasetAuditError(f"invalid evaluation case at line {line_number}: {exc}") from exc
    return cases


def _cross_split_values(
    cases: Iterable[EvaluationCase], getter: Callable[[EvaluationCase], Iterable[str]]
) -> list[str]:
    splits_by_value: dict[str, set[str]] = defaultdict(set)
    for case in cases:
        for value in getter(case):
            splits_by_value[value].add(case.split.value)
    return sorted(value for value, splits in splits_by_value.items() if len(splits) > 1)


def audit_cases(
    cases: list[EvaluationCase], *, dataset_version: str
) -> DatasetBuildManifest:
    case_ids = [case.case_id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise DatasetAuditError("duplicate case_id detected")

    leakage = SplitLeakage(
        paper_ids=_cross_split_values(cases, lambda case: case.paper_ids),
        conversation_ids=_cross_split_values(cases, lambda case: case.conversation_ids),
        text_fingerprints=_cross_split_values(
            cases, lambda case: [case.deduplication.text_fingerprint]
        ),
        embedding_cluster_ids=_cross_split_values(
            cases, lambda case: [case.deduplication.embedding_cluster_id]
        ),
        paper_source_cluster_ids=_cross_split_values(
            cases, lambda case: [case.deduplication.paper_source_cluster_id]
        ),
    )
    labels = (
        ("paper_id", leakage.paper_ids),
        ("conversation_id", leakage.conversation_ids),
        ("text fingerprint", leakage.text_fingerprints),
        ("embedding near-duplicate", leakage.embedding_cluster_ids),
        ("paper source", leakage.paper_source_cluster_ids),
    )
    violations = [f"{label}: {values}" for label, values in labels if values]
    if violations:
        raise DatasetAuditError("cross-split leakage detected; " + "; ".join(violations))

    canonical = [case.model_dump(mode="json") for case in sorted(cases, key=lambda item: item.case_id)]
    cases_sha256 = hashlib.sha256(
        json.dumps(canonical, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    traceable = sum(
        bool(
            case.source.source_id
            and case.source.provenance_uri
            and case.source.license
            and case.source.build_version
        )
        for case in cases
    )
    return DatasetBuildManifest(
        dataset_version=dataset_version,
        case_count=len(cases),
        split_counts=dict(sorted(Counter(case.split.value for case in cases).items())),
        difficulty_counts=dict(
            sorted(Counter(case.difficulty.value for case in cases).items())
        ),
        task_family_counts=dict(sorted(Counter(case.task_family for case in cases).items())),
        traceable_case_rate=traceable / len(cases) if cases else 1.0,
        cases_sha256=cases_sha256,
        leakage=leakage,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit an evaluation JSONL dataset")
    parser.add_argument("input", type=Path)
    parser.add_argument("--dataset-version", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    manifest = audit_cases(load_cases(args.input), dataset_version=args.dataset_version)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
