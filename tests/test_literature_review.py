from academic_tasks.literature_review import LiteratureReviewService, ReviewClaim
from academic_tasks.writing_brief import (
    EvidenceMapItem,
    SourceMaterial,
    StatementKind,
    WritingBriefBuilder,
)


def evidence_map(index: int = 0) -> list[EvidenceMapItem]:
    brief = WritingBriefBuilder().build(
        section_type="related_work",
        target_language="zh",
        target_length=1200,
        style="academic",
        user_points=["比较方法"],
        materials=[
            SourceMaterial(
                source_id=f"paper-{index}-a",
                text=f"Method A achieved {90 + index % 10}%.",
                kind=StatementKind.FACT,
                evidence_ids=[f"EA-{index}"],
            ),
            SourceMaterial(
                source_id=f"paper-{index}-b",
                text="Method B uses less training data.",
                kind=StatementKind.FACT,
                evidence_ids=[f"EB-{index}"],
            ),
        ],
        immutable_items=[],
    )
    return brief.evidence_map


def test_review_builds_evidence_matrix_before_draft() -> None:
    items = evidence_map()
    result = LiteratureReviewService().build(
        items,
        themes={"performance": [items[0].statement_id], "efficiency": [items[1].statement_id]},
        inferences=["这些结果可能反映数据效率差异。"],
    )

    assert len(result.evidence_matrix) == 2
    assert result.evidence_matrix[0].evidence_ids
    assert "[EA-0]" in result.draft
    assert "推断：" in result.draft
    assert result.review_required
    assert result.verification_errors == []


def test_unsupported_fact_is_rejected_by_citation_verifier() -> None:
    errors = LiteratureReviewService.verify(
        [
            ReviewClaim(
                text="Unsupported fact",
                kind=StatementKind.FACT,
                evidence_ids=[],
                traceable=False,
            )
        ]
    )

    assert len(errors) == 2


def test_all_review_facts_are_traceable_or_marked_inference() -> None:
    service = LiteratureReviewService()
    traceable = total = 0
    for index in range(100):
        items = evidence_map(index)
        result = service.build(
            items,
            themes={"methods": [item.statement_id for item in items]},
            inferences=[f"这些差异可能与数据规模 {index} 有关。"],
        )
        for claim in result.claims:
            total += 1
            traceable += int(
                (
                    claim.kind is StatementKind.FACT
                    and claim.traceable
                    and bool(claim.evidence_ids)
                )
                or (
                    claim.kind is StatementKind.INFERENCE
                    and f"推断：{claim.text}" in result.draft
                )
            )

    assert traceable / total == 1.0
