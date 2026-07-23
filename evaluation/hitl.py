"""Offline, human-gated failure-to-data staging workflow.

The module never mutates production prompts or model weights. It stores only
reviewable metadata and requires authorization, anonymization, human approval,
regression and safety evidence before a version can be promoted.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections import Counter
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from evaluation.datasets.schema import AuthorizationStatus
from evaluation.experiments import ErrorCategory, ExperimentResult


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReviewDecision(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"


class FailureCluster(_StrictModel):
    category: ErrorCategory
    count: int = Field(ge=1)
    case_ids: list[str] = Field(min_length=1)
    error_codes: list[str] = Field(default_factory=list)


class FailureClusterer:
    """Cluster failed results using the closed L04 taxonomy.

    Output and Trace payloads are intentionally excluded from the cluster view.
    """

    def cluster(
        self, results: list[ExperimentResult]
    ) -> dict[ErrorCategory, FailureCluster]:
        failed = [item for item in results if not item.passed]
        counts = Counter(item.error_category or ErrorCategory.SYSTEM for item in failed)
        return {
            category: FailureCluster(
                category=category,
                count=count,
                case_ids=sorted(
                    item.case_id
                    for item in failed
                    if (item.error_category or ErrorCategory.SYSTEM) is category
                ),
                error_codes=sorted(
                    {
                        item.error_code or "unclassified_exception"
                        for item in failed
                        if (item.error_category or ErrorCategory.SYSTEM) is category
                    }
                ),
            )
            for category, count in sorted(counts.items(), key=lambda item: item[0].value)
        }


class CandidateSource(_StrictModel):
    source_id: str = Field(min_length=1)
    provenance_uri: str = Field(min_length=1)
    authorization_status: AuthorizationStatus
    license: str = Field(min_length=1)
    build_version: str = Field(min_length=1)
    private_data: bool = False
    consent_id: str | None = None
    anonymized: bool = False

    @model_validator(mode="after")
    def validate_private_source(self) -> CandidateSource:
        if self.private_data or self.authorization_status is AuthorizationStatus.PRIVATE_CONSENTED:
            if self.authorization_status is not AuthorizationStatus.PRIVATE_CONSENTED:
                raise ValueError("private data requires private_consented authorization")
            if not self.consent_id:
                raise ValueError("private data requires explicit consent")
            if not self.anonymized:
                raise ValueError("private data must be anonymized before staging")
        return self


class HumanReview(_StrictModel):
    reviewer_id: str = Field(min_length=1)
    decision: ReviewDecision
    rationale: str = Field(min_length=1)
    reviewed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class StagingCandidate(_StrictModel):
    candidate_id: str = Field(min_length=1)
    failure_case_id: str = Field(min_length=1)
    error_category: ErrorCategory
    source: CandidateSource
    public_context: dict[str, str]
    proposed_change: str = Field(min_length=1)
    created_by: str = Field(min_length=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    review: HumanReview | None = None

    @model_validator(mode="after")
    def validate_public_context(self) -> StagingCandidate:
        allowed = {"task_family", "difficulty", "language", "model", "error_code"}
        unknown = set(self.public_context) - allowed
        if unknown:
            raise ValueError(f"public_context contains non-review fields: {sorted(unknown)}")
        return self


class PromotionGateResult(_StrictModel):
    regression_passed: bool
    safety_passed: bool
    regression_report: str | None = None
    safety_report: str | None = None

    @model_validator(mode="after")
    def require_reports_for_passing_gate(self) -> PromotionGateResult:
        if self.regression_passed and self.safety_passed and (
            not self.regression_report or not self.safety_report
        ):
            raise ValueError("passing gates require versioned regression and safety reports")
        return self


class PromotionReport(_StrictModel):
    version: str = Field(min_length=1)
    previous_version: str | None
    candidate_ids: list[str] = Field(min_length=1)
    promoted_by: str = Field(min_length=1)
    promoted_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    gate: PromotionGateResult
    change_summary: dict[str, int]
    production_mutation: bool = False


class PromotionGateRunner(Protocol):
    def __call__(
        self, version: str, candidates: list[StagingCandidate]
    ) -> PromotionGateResult: ...


class RollbackRecord(_StrictModel):
    from_version: str | None
    target_version: str | None
    rolled_back_by: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    rolled_back_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class StagingRegistry:
    """File-backed audit registry for offline staging and version promotion."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.candidate_dir = root / "candidates"
        self.promotion_dir = root / "promotions"
        self.candidate_dir.mkdir(parents=True, exist_ok=True)
        self.promotion_dir.mkdir(parents=True, exist_ok=True)

    def stage(self, candidate: StagingCandidate) -> None:
        if candidate.source.authorization_status is AuthorizationStatus.UNAUTHORIZED:
            raise ValueError("unauthorized source cannot enter staging")
        path = self.candidate_dir / f"{_safe_name(candidate.candidate_id)}.json"
        if path.exists():
            raise ValueError("candidate_id already exists")
        _atomic_json(path, candidate.model_dump(mode="json"))

    def get(self, candidate_id: str) -> StagingCandidate:
        path = self.candidate_dir / f"{_safe_name(candidate_id)}.json"
        if not path.exists():
            raise KeyError(candidate_id)
        return StagingCandidate.model_validate_json(path.read_text("utf-8"))

    def list_candidates(self) -> list[StagingCandidate]:
        return [
            StagingCandidate.model_validate_json(path.read_text("utf-8"))
            for path in sorted(self.candidate_dir.glob("*.json"))
        ]

    def review(self, candidate_id: str, review: HumanReview) -> StagingCandidate:
        candidate = self.get(candidate_id)
        updated = candidate.model_copy(update={"review": review})
        _atomic_json(
            self.candidate_dir / f"{_safe_name(candidate_id)}.json",
            updated.model_dump(mode="json"),
        )
        return updated

    def promote(
        self,
        candidate_ids: list[str],
        *,
        version: str,
        gate_runner: PromotionGateRunner,
        promoted_by: str,
    ) -> PromotionReport:
        candidates = [self.get(candidate_id) for candidate_id in candidate_ids]
        if not candidates:
            raise ValueError("promotion requires at least one candidate")
        if any(
            candidate.review is None
            or candidate.review.decision is not ReviewDecision.APPROVED
            for candidate in candidates
        ):
            raise ValueError("all candidates must be human approved")
        if any(
            candidate.source.authorization_status is AuthorizationStatus.UNAUTHORIZED
            for candidate in candidates
        ):
            raise ValueError("unauthorized candidate cannot be promoted")
        gate = gate_runner(version, candidates)
        if not gate.regression_passed or not gate.safety_passed:
            raise ValueError("promotion requires regression and safety gates")
        path = self.promotion_dir / f"{_safe_name(version)}.json"
        if path.exists():
            raise ValueError("promotion version already exists")
        previous = self.current_version()
        report = PromotionReport(
            version=version,
            previous_version=previous,
            candidate_ids=sorted(candidate_ids),
            promoted_by=promoted_by,
            gate=gate,
            change_summary=dict(
                sorted(Counter(item.error_category.value for item in candidates).items())
            ),
        )
        _atomic_json(path, report.model_dump(mode="json"))
        _atomic_json(self.root / "current.json", {"version": version})
        return report

    def current_version(self) -> str | None:
        path = self.root / "current.json"
        if not path.exists():
            return None
        value = json.loads(path.read_text("utf-8")).get("version")
        return str(value) if value is not None else None

    def rollback(
        self,
        *,
        target_version: str | None,
        rolled_back_by: str,
        reason: str,
    ) -> RollbackRecord:
        if target_version is not None and not (
            self.promotion_dir / f"{_safe_name(target_version)}.json"
        ).exists():
            raise ValueError("rollback target version does not exist")
        record = RollbackRecord(
            from_version=self.current_version(),
            target_version=target_version,
            rolled_back_by=rolled_back_by,
            reason=reason,
        )
        _atomic_json(self.root / "current.json", {"version": target_version})
        with (self.root / "rollbacks.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(record.model_dump_json() + "\n")
        return record


def _safe_name(value: str) -> str:
    normalized = "".join(character for character in value if character.isalnum() or character in "-_.")
    if not normalized or normalized != value:
        raise ValueError("identifier contains unsafe characters")
    return normalized


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
