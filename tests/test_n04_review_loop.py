from __future__ import annotations

from typing import Any

import pytest

from backend.subagents.review_loop import (
    ClaimRecord,
    CriticIssue,
    CriticReport,
    DraftArtifact,
    DraftClaim,
    EvidenceMatrix,
    IssueResolution,
    ReviewLoop,
    ReviewStatus,
    VerificationFinding,
    VerificationReport,
    conflict_metrics,
)


class FixtureCritic:
    async def review(self, matrix: EvidenceMatrix) -> CriticReport:
        issues = [
            CriticIssue(
                issue_id=f"issue-{index}",
                issue_type="conflict",
                claim_ids=[f"claim-{index}"],
                evidence_refs=[f"E{index}"],
                description="conflicting outcomes require disclosure",
                conflict_id=f"conflict-{index}",
            )
            for index in range(18)
        ]
        issues.extend(
            CriticIssue(
                issue_id=f"false-{index}",
                issue_type="conflict",
                claim_ids=["claim-0"],
                evidence_refs=["E0"],
                description="candidate conflict",
                conflict_id=f"false-conflict-{index}",
            )
            for index in range(2)
        )
        return CriticReport(issues=issues)


class FixtureWriter:
    def __init__(self) -> None:
        self.write_calls = 0
        self.revision_calls = 0

    async def write(self, matrix: EvidenceMatrix, report: CriticReport) -> DraftArtifact:
        self.write_calls += 1
        claims = [
            DraftClaim(
                claim_id=claim.claim_id,
                text=claim.text,
                evidence_refs=claim.evidence_refs,
                inferred=claim.inferred,
            )
            for claim in matrix.claims
        ]
        claims.extend(
            [
                DraftClaim(claim_id="unsupported-1", text="unsupported one"),
                DraftClaim(claim_id="unsupported-2", text="unsupported two"),
            ]
        )
        return DraftArtifact(
            claims=claims,
            issue_resolutions=[
                IssueResolution(
                    issue_id=issue.issue_id,
                    status="unresolved" if issue.issue_id == "issue-0" else "accepted",
                    rationale="disclosed" if issue.issue_id == "issue-0" else "addressed",
                )
                for issue in report.issues
            ],
        )

    async def revise(
        self, draft: DraftArtifact, findings: list[VerificationFinding]
    ) -> DraftArtifact:
        self.revision_calls += 1
        bad_ids = {finding.claim_id for finding in findings if finding.severity == "severe"}
        return draft.model_copy(
            update={"claims": [claim for claim in draft.claims if claim.claim_id not in bad_ids]}
        )


class DeterministicVerifier:
    async def verify(
        self, draft: DraftArtifact, matrix: EvidenceMatrix
    ) -> VerificationReport:
        known = {claim.claim_id: claim for claim in matrix.claims}
        findings: list[VerificationFinding] = []
        for claim in draft.claims:
            source = known.get(claim.claim_id)
            if source is None and not claim.inferred:
                findings.append(
                    VerificationFinding(
                        claim_id=claim.claim_id,
                        finding_type="unsupported",
                        severity="severe",
                        description="claim has no Evidence Matrix row or inference label",
                    )
                )
            elif source is not None and not set(claim.evidence_refs) <= set(source.evidence_refs):
                findings.append(
                    VerificationFinding(
                        claim_id=claim.claim_id,
                        finding_type="citation_mismatch",
                        severity="severe",
                        description="citation is not in the matrix",
                    )
                )
        return VerificationReport(findings=findings)


def _matrix() -> EvidenceMatrix:
    return EvidenceMatrix(
        claims=[
            ClaimRecord(
                claim_id=f"claim-{index}",
                text=f"supported claim {index}",
                evidence_refs=[f"E{index}"],
            )
            for index in range(100)
        ],
        conflict_ids=[f"conflict-{index}" for index in range(20)],
    )


@pytest.mark.asyncio
async def test_bounded_critic_writer_verifier_loop_meets_quality_gates() -> None:
    writer = FixtureWriter()
    result = await ReviewLoop(FixtureCritic(), writer, DeterministicVerifier()).run(_matrix())
    assert result.status is ReviewStatus.COMPLETED
    assert result.critic_rounds == 1
    assert result.verifier_revision_rounds == 1
    assert writer.write_calls == 1
    assert writer.revision_calls == 1
    assert all(resolution.status != "open" for resolution in result.draft.issue_resolutions)
    assert result.severe_unsupported_rate < 0.03
    assert result.conflict_recall >= 0.85
    assert result.conflict_precision >= 0.80
    assert "conflict-0" in result.disclosed_conflict_ids
    assert all(
        claim.inferred or claim.claim_id.startswith("claim-") for claim in result.draft.claims
    )


def test_conflict_metrics_use_explicit_denominators() -> None:
    metrics: dict[str, Any] = conflict_metrics(
        predicted={"a", "b", "extra"}, gold={"a", "b", "c"}
    )
    assert metrics == {"true_positive": 2, "predicted": 3, "gold": 3, "precision": 2 / 3, "recall": 2 / 3}
