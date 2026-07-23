"""Bounded Critic—Writer—Verifier collaboration over an Evidence Matrix."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ClaimRecord(_StrictModel):
    claim_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    evidence_refs: list[str] = Field(default_factory=list)
    inferred: bool = False


class EvidenceMatrix(_StrictModel):
    claims: list[ClaimRecord]
    conflict_ids: list[str] = Field(default_factory=list)


class CriticIssue(_StrictModel):
    issue_id: str = Field(min_length=1)
    issue_type: Literal["coverage_gap", "conflict", "non_comparable", "unsupported"]
    claim_ids: list[str]
    evidence_refs: list[str]
    description: str = Field(min_length=1)
    conflict_id: str | None = None


class CriticReport(_StrictModel):
    issues: list[CriticIssue]


class IssueResolution(_StrictModel):
    issue_id: str = Field(min_length=1)
    status: Literal["open", "accepted", "rejected", "unresolved"] = "open"
    rationale: str = Field(min_length=1)


class DraftClaim(_StrictModel):
    claim_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    evidence_refs: list[str] = Field(default_factory=list)
    inferred: bool = False


class DraftArtifact(_StrictModel):
    claims: list[DraftClaim]
    issue_resolutions: list[IssueResolution]


class VerificationFinding(_StrictModel):
    claim_id: str = Field(min_length=1)
    finding_type: Literal[
        "unsupported", "missing_citation", "citation_mismatch", "numeric_mismatch", "unmarked_inference"
    ]
    severity: Literal["warning", "severe"]
    description: str = Field(min_length=1)


class VerificationReport(_StrictModel):
    findings: list[VerificationFinding]


class ReviewStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"


class ReviewResult(_StrictModel):
    status: ReviewStatus
    draft: DraftArtifact
    critic_report: CriticReport
    verification_report: VerificationReport
    critic_rounds: int = Field(ge=0, le=1)
    verifier_revision_rounds: int = Field(ge=0, le=1)
    severe_unsupported_rate: float = Field(ge=0, le=1)
    conflict_precision: float = Field(ge=0, le=1)
    conflict_recall: float = Field(ge=0, le=1)
    disclosed_conflict_ids: list[str]


class CriticPort(Protocol):
    async def review(self, matrix: EvidenceMatrix) -> CriticReport: ...


class WriterPort(Protocol):
    async def write(self, matrix: EvidenceMatrix, report: CriticReport) -> DraftArtifact: ...

    async def revise(
        self, draft: DraftArtifact, findings: list[VerificationFinding]
    ) -> DraftArtifact: ...


class VerifierPort(Protocol):
    async def verify(
        self, draft: DraftArtifact, matrix: EvidenceMatrix
    ) -> VerificationReport: ...


class ReviewLoop:
    """Executes exactly one Critic pass and at most one Verifier-driven revision."""

    def __init__(
        self, critic: CriticPort, writer: WriterPort, verifier: VerifierPort
    ) -> None:
        self._critic = critic
        self._writer = writer
        self._verifier = verifier

    async def run(self, matrix: EvidenceMatrix) -> ReviewResult:
        critic_report = await self._critic.review(matrix)
        draft = await self._writer.write(matrix, critic_report)
        _validate_issue_resolutions(critic_report, draft)

        verification = await self._verified(draft, matrix)
        severe = [item for item in verification.findings if item.severity == "severe"]
        revision_rounds = 0
        if severe:
            draft = await self._writer.revise(draft, severe)
            revision_rounds = 1
            _validate_issue_resolutions(critic_report, draft)
            verification = await self._verified(draft, matrix)

        severe_count = sum(item.severity == "severe" for item in verification.findings)
        severe_rate = severe_count / len(draft.claims) if draft.claims else 0.0
        predicted_conflicts = {
            issue.conflict_id
            for issue in critic_report.issues
            if issue.issue_type == "conflict" and issue.conflict_id
        }
        metrics = conflict_metrics(predicted_conflicts, set(matrix.conflict_ids))
        resolutions = {item.issue_id: item for item in draft.issue_resolutions}
        disclosed = sorted(
            issue.conflict_id
            for issue in critic_report.issues
            if issue.conflict_id
            and issue.issue_id in resolutions
            and resolutions[issue.issue_id].status == "unresolved"
        )
        all_traceable = not _traceability_findings(draft, matrix)
        status = (
            ReviewStatus.COMPLETED
            if severe_rate < 0.03
            and float(metrics["recall"]) >= 0.85
            and float(metrics["precision"]) >= 0.80
            and all_traceable
            else ReviewStatus.FAILED
        )
        return ReviewResult(
            status=status,
            draft=draft,
            critic_report=critic_report,
            verification_report=verification,
            critic_rounds=1,
            verifier_revision_rounds=revision_rounds,
            severe_unsupported_rate=severe_rate,
            conflict_precision=float(metrics["precision"]),
            conflict_recall=float(metrics["recall"]),
            disclosed_conflict_ids=disclosed,
        )

    async def _verified(
        self, draft: DraftArtifact, matrix: EvidenceMatrix
    ) -> VerificationReport:
        external = await self._verifier.verify(draft, matrix)
        internal = _traceability_findings(draft, matrix)
        by_key = {
            (finding.claim_id, finding.finding_type): finding
            for finding in [*external.findings, *internal]
        }
        return VerificationReport(findings=list(by_key.values()))


def _validate_issue_resolutions(report: CriticReport, draft: DraftArtifact) -> None:
    expected = {issue.issue_id for issue in report.issues}
    resolutions = {item.issue_id: item for item in draft.issue_resolutions}
    if set(resolutions) != expected or any(item.status == "open" for item in resolutions.values()):
        raise ValueError("Every Critic issue requires a non-open Writer resolution")


def _traceability_findings(
    draft: DraftArtifact, matrix: EvidenceMatrix
) -> list[VerificationFinding]:
    known = {claim.claim_id: claim for claim in matrix.claims}
    findings: list[VerificationFinding] = []
    for claim in draft.claims:
        source = known.get(claim.claim_id)
        if source is None and not claim.inferred:
            findings.append(
                VerificationFinding(
                    claim_id=claim.claim_id,
                    finding_type="unmarked_inference",
                    severity="severe",
                    description="Claim is absent from Evidence Matrix and is not labelled inference",
                )
            )
        elif source is not None and not set(claim.evidence_refs) <= set(source.evidence_refs):
            findings.append(
                VerificationFinding(
                    claim_id=claim.claim_id,
                    finding_type="citation_mismatch",
                    severity="severe",
                    description="Claim citation does not resolve to its Evidence Matrix row",
                )
            )
    return findings


def conflict_metrics(
    predicted: set[str], gold: set[str]
) -> dict[str, int | float]:
    true_positive = len(predicted & gold)
    precision = true_positive / len(predicted) if predicted else (1.0 if not gold else 0.0)
    recall = true_positive / len(gold) if gold else 1.0
    return {
        "true_positive": true_positive,
        "predicted": len(predicted),
        "gold": len(gold),
        "precision": precision,
        "recall": recall,
    }
