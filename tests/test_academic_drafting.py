from academic_tasks.drafting import AcademicDrafter
from academic_tasks.writing_brief import (
    SourceMaterial,
    StatementKind,
    WritingBriefBuilder,
)


def brief(section_type: str, index: int = 0):
    points = [f"point-{index}-{position}" for position in range(5)]
    materials = [
        SourceMaterial(
            source_id=f"source-{index}-{position}",
            text=f"Supported fact {index}-{position} equals {90 + position}%.",
            kind=StatementKind.FACT,
            evidence_ids=[f"E{index}-{position}"],
        )
        for position in range(5)
    ]
    return WritingBriefBuilder().build(
        section_type=section_type,
        target_language="zh",
        target_length=1000,
        style="academic",
        user_points=points,
        materials=materials,
        immutable_items=[f"{90 + position}%" for position in range(5)],
    )


def test_all_section_types_have_plan_sources_and_review_marker() -> None:
    drafter = AcademicDrafter()
    for section_type in drafter.SECTION_PURPOSES:
        result = drafter.draft(brief(section_type))
        assert len(result.paragraph_plan) >= 2
        assert len(result.paragraphs) == len(result.paragraph_plan)
        assert result.review_required
        assert all(paragraph.evidence_ids for paragraph in result.paragraphs)
        assert all(paragraph.source_statement_ids for paragraph in result.paragraphs)


def test_drafting_evaluation_thresholds() -> None:
    drafter = AcademicDrafter()
    covered = total_points = structured = coherent = unsupported = total_facts = 0
    section_types = list(drafter.SECTION_PURPOSES)
    for index in range(100):
        item = brief(section_types[index % len(section_types)], index)
        result = drafter.draft(item)
        text = " ".join(paragraph.text for paragraph in result.paragraphs)
        covered += sum(point in text for point in item.user_points)
        total_points += len(item.user_points)
        structured += int(len(result.paragraph_plan) >= 2 and len(result.paragraphs) >= 2)
        coherent += int(
            all(
                plan.purpose in paragraph.text
                for plan, paragraph in zip(result.paragraph_plan, result.paragraphs)
            )
        )
        allowed_texts = {
            evidence.text for evidence in item.evidence_map if evidence.allowed_as_fact
        }
        for paragraph in result.paragraphs:
            for statement_id in paragraph.source_statement_ids:
                statement = next(
                    evidence
                    for evidence in item.evidence_map
                    if evidence.statement_id == statement_id
                )
                total_facts += 1
                unsupported += int(statement.text not in allowed_texts)

    assert covered / total_points >= 0.90
    assert structured / 100 * 5 >= 4
    assert coherent / 100 * 5 >= 4
    assert unsupported / max(1, total_facts) < 0.03


def test_paragraph_drafting_dataset_size() -> None:
    drafter = AcademicDrafter()
    paragraphs = []
    for index in range(100):
        paragraphs.extend(drafter.draft(brief("discussion", index)).paragraphs)
    assert len(paragraphs) >= 200
