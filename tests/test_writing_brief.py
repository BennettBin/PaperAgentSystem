from academic_tasks.writing_brief import (
    SourceMaterial,
    StatementKind,
    WritingBriefBuilder,
)


def materials(index: int = 0) -> list[SourceMaterial]:
    return [
        SourceMaterial(
            source_id=f"user-{index}",
            text=f"The accuracy is {90 + index % 10}%.",
            kind=StatementKind.FACT,
            evidence_ids=[f"ev-{index}"],
        ),
        SourceMaterial(
            source_id=f"user-opinion-{index}",
            text="This approach is elegant.",
            kind=StatementKind.OPINION,
        ),
        SourceMaterial(
            source_id=f"agent-inference-{index}",
            text="The result may generalize.",
            kind=StatementKind.INFERENCE,
            evidence_ids=[f"ev-{index}"],
        ),
    ]


def test_writing_brief_classifies_facts_and_requires_sources() -> None:
    brief = WritingBriefBuilder().build(
        section_type="results",
        target_language="zh",
        target_length=800,
        style="academic",
        user_points=["报告准确率", "讨论局限"],
        materials=materials(),
        immutable_items=["90%", "Dataset-A"],
    )

    assert brief.user_points == ["报告准确率", "讨论局限"]
    assert brief.evidence_map[0].allowed_as_fact
    assert not brief.evidence_map[1].allowed_as_fact
    assert not brief.evidence_map[2].allowed_as_fact
    assert brief.immutable_items == ["90%", "Dataset-A"]


def test_all_allowed_facts_have_sources() -> None:
    brief = WritingBriefBuilder().build(
        section_type="methods",
        target_language="en",
        target_length=500,
        style="academic",
        user_points=["method"],
        materials=materials(),
        immutable_items=[],
    )

    assert all(
        item.source_ids and item.evidence_ids
        for item in brief.evidence_map
        if item.allowed_as_fact
    )


def test_user_point_recall_threshold() -> None:
    builder = WritingBriefBuilder()
    recalled = total = 0
    for index in range(100):
        points = [f"point-{index}-{position}" for position in range(5)]
        brief = builder.build(
            section_type="discussion",
            target_language="zh",
            target_length=1000,
            style="academic",
            user_points=points,
            materials=materials(index),
            immutable_items=[],
        )
        recalled += len(set(points) & set(brief.user_points))
        total += len(points)

    assert recalled / total >= 0.95
