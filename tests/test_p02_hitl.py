from pathlib import Path

import pytest

from evaluation.datasets.schema import AuthorizationStatus
from evaluation.experiments import ErrorCategory, ExperimentResult
from evaluation.hitl import (
    CandidateSource,
    FailureClusterer,
    HumanReview,
    PromotionGateResult,
    ReviewDecision,
    StagingCandidate,
    StagingRegistry,
)


def _result(case_id: str, code: str) -> ExperimentResult:
    return ExperimentResult(
        case_id=case_id,
        task_id=f"task-{case_id}",
        system_id="candidate-v1",
        passed=False,
        error_code=code,
    )


def _source(**updates: object) -> CandidateSource:
    payload: dict[str, object] = {
        "source_id": "eval-public-1",
        "provenance_uri": "evaluation/reports/run-1/cases/case-1.json",
        "authorization_status": AuthorizationStatus.PUBLIC,
        "license": "Apache-2.0",
        "build_version": "run-1",
        "private_data": False,
        "consent_id": None,
        "anonymized": True,
    }
    payload.update(updates)
    return CandidateSource.model_validate(payload)


def test_failure_extraction_clusters_closed_taxonomy_without_private_payload() -> None:
    clusters = FailureClusterer().cluster(
        [
            _result("case-a", "retrieval_empty"),
            _result("case-b", "citation_missing"),
            _result("case-c", "retrieval_timeout"),
        ]
    )

    assert clusters[ErrorCategory.RETRIEVAL].count == 2
    assert clusters[ErrorCategory.VERIFICATION].count == 1
    serialized = str(clusters)
    assert "output" not in serialized
    assert "trace" not in serialized


def test_private_or_unauthorized_data_fails_closed_before_staging(tmp_path: Path) -> None:
    registry = StagingRegistry(tmp_path)
    with pytest.raises(ValueError, match="unauthorized"):
        registry.stage(
            StagingCandidate(
                candidate_id="bad-1",
                failure_case_id="case-1",
                error_category=ErrorCategory.DATA,
                source=_source(
                    authorization_status=AuthorizationStatus.UNAUTHORIZED,
                    anonymized=False,
                ),
                public_context={"task_family": "qa"},
                proposed_change="exclude bad source",
                created_by="reviewer-a",
            )
        )
    with pytest.raises(ValueError, match="consent"):
        _source(
            authorization_status=AuthorizationStatus.PRIVATE_CONSENTED,
            private_data=True,
            consent_id=None,
        )
    with pytest.raises(ValueError, match="anonymized"):
        _source(
            authorization_status=AuthorizationStatus.PRIVATE_CONSENTED,
            private_data=True,
            consent_id="consent-1",
            anonymized=False,
        )


def test_reviewed_candidate_stays_in_staging_until_human_approved(tmp_path: Path) -> None:
    registry = StagingRegistry(tmp_path)
    candidate = StagingCandidate(
        candidate_id="candidate-1",
        failure_case_id="case-1",
        error_category=ErrorCategory.RETRIEVAL,
        source=_source(),
        public_context={"task_family": "single_paper_qa", "difficulty": "L3"},
        proposed_change="add a development-only retrieval example",
        created_by="reviewer-a",
    )
    registry.stage(candidate)

    assert registry.get("candidate-1").review is None
    with pytest.raises(ValueError, match="approved"):
        registry.promote(
            ["candidate-1"],
            version="dataset-v2",
            gate_runner=lambda _version, _candidates: PromotionGateResult(
                regression_passed=True,
                safety_passed=True,
                regression_report="regression.json",
                safety_report="safety.json",
            ),
            promoted_by="reviewer-b",
        )

    registry.review(
        "candidate-1",
        HumanReview(
            reviewer_id="reviewer-b",
            decision=ReviewDecision.APPROVED,
            rationale="authorized, anonymized and useful",
        ),
    )
    assert registry.get("candidate-1").review is not None
    assert registry.current_version() is None


def test_promotion_runs_both_gates_writes_change_report_and_rolls_back(
    tmp_path: Path,
) -> None:
    registry = StagingRegistry(tmp_path)
    registry.stage(
        StagingCandidate(
            candidate_id="candidate-1",
            failure_case_id="case-1",
            error_category=ErrorCategory.GENERATION,
            source=_source(),
            public_context={"task_family": "comparison"},
            proposed_change="add reviewed counterexample",
            created_by="reviewer-a",
        )
    )
    registry.review(
        "candidate-1",
        HumanReview(
            reviewer_id="reviewer-b",
            decision=ReviewDecision.APPROVED,
            rationale="safe development data",
        ),
    )

    gate_calls: list[str] = []

    def failing_gate(version, _candidates):
        gate_calls.append(version)
        return PromotionGateResult(regression_passed=True, safety_passed=False)

    with pytest.raises(ValueError, match="regression and safety"):
        registry.promote(
            ["candidate-1"],
            version="dataset-v2",
            gate_runner=failing_gate,
            promoted_by="reviewer-b",
        )

    def passing_gate(version, _candidates):
        gate_calls.append(version)
        return PromotionGateResult(
            regression_passed=True,
            safety_passed=True,
            regression_report="evaluation/reports/regression-v2/report.json",
            safety_report="evaluation/reports/security-v2/report.json",
        )

    report = registry.promote(
        ["candidate-1"],
        version="dataset-v2",
        gate_runner=passing_gate,
        promoted_by="reviewer-b",
    )

    assert report.candidate_ids == ["candidate-1"]
    assert report.previous_version is None
    assert gate_calls == ["dataset-v2", "dataset-v2"]
    assert registry.current_version() == "dataset-v2"
    assert (tmp_path / "promotions" / "dataset-v2.json").exists()
    registry.rollback(target_version=None, rolled_back_by="reviewer-c", reason="regression")
    assert registry.current_version() is None
    assert (tmp_path / "rollbacks.jsonl").exists()
