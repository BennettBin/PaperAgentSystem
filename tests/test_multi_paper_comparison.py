from academic_tasks.comparison import MultiPaperComparator, PaperCardRecord
from subagents.manager import ChildStatus, ChildTask, SubAgentBatchResult
from subagents.paper_reader import PaperCard, PaperEvidence


def card(index: int) -> PaperCard:
    accuracy = 90 + index
    return PaperCard(
        title=f"Paper {index}",
        research_question="RQ",
        methodology=f"Method {index}",
        datasets=[f"Dataset {index}"],
        metrics=["Accuracy"],
        results=[f"Accuracy {accuracy}%"],
        contributions=[f"Contribution {index}"],
        limitations=[f"Limitation {index}"],
        evidence=[
            PaperEvidence(
                evidence_id=f"ev-{index}-{field}",
                field=field,
                quote=(
                    f"Accuracy {accuracy}%"
                    if field == "results"
                    else f"{field}: {getattr_value(field, index)}"
                ),
                page=index + 1,
            )
            for field in (
                "methodology",
                "datasets",
                "metrics",
                "results",
                "contributions",
                "limitations",
            )
        ],
        missing_fields=[],
    )


def getattr_value(field: str, index: int) -> str:
    return {
        "methodology": f"Method {index}",
        "datasets": f"Dataset {index}",
        "metrics": "Accuracy",
        "contributions": f"Contribution {index}",
        "limitations": f"Limitation {index}",
    }.get(field, "")


def test_comparison_matrix_preserves_evidence_and_numbers() -> None:
    result = MultiPaperComparator().compare(
        [PaperCardRecord(f"file-{index}", card(index)) for index in range(3)],
        ["methodology", "datasets", "results"],
    )

    assert len(result.matrix) == 9
    assert all(cell.evidence_ids for cell in result.matrix)
    assert all(cell.numbers_verified for cell in result.matrix)
    assert all(conclusion.evidence_ids for conclusion in result.conclusions)


def test_comparison_evaluation_thresholds() -> None:
    comparator = MultiPaperComparator()
    dimensions = ["methodology", "datasets", "metrics", "results", "limitations"]
    coverage_scores = []
    numeric_cells = correct_numeric = conclusions = supported = 0
    for repeat in range(20):
        papers = [PaperCardRecord(f"file-{index}", card(index)) for index in range(5)]
        result = comparator.compare(papers, dimensions)
        expected_cells = len(papers) * len(dimensions)
        covered = sum(bool(cell.values) for cell in result.matrix)
        coverage_scores.append(covered / expected_cells)
        for cell in result.matrix:
            if any(char.isdigit() for value in cell.values for char in value):
                numeric_cells += 1
                correct_numeric += int(cell.numbers_verified)
        conclusions += len(result.conclusions)
        supported += sum(bool(item.evidence_ids) for item in result.conclusions)

    assert sum(coverage_scores) / len(coverage_scores) >= 0.90
    assert correct_numeric / numeric_cells >= 0.95
    assert supported / conclusions >= 0.90


def test_unverified_number_is_not_promoted_to_conclusion() -> None:
    value = card(1)
    value.results = ["Accuracy 99%"]
    result = MultiPaperComparator().compare(
        [PaperCardRecord("file-1", value)],
        ["results"],
    )

    assert not result.matrix[0].numbers_verified
    assert result.conclusions == []


def test_comparator_consumes_parallel_subagent_batch_and_keeps_partial_success() -> None:
    completed = tuple(
        ChildTask(
            child_task_id=f"child-{index}",
            parent_task_id="parent",
            workspace_id="ws",
            file_id=f"file-{index}",
            status=ChildStatus.COMPLETED,
            result={"card": card(index).model_dump(mode="json")},
        )
        for index in range(2)
    )
    failed = (
        ChildTask(
            child_task_id="child-failed",
            parent_task_id="parent",
            workspace_id="ws",
            file_id="file-failed",
            status=ChildStatus.FAILED,
            error="parse failed",
        ),
    )
    batch = SubAgentBatchResult("parent", completed, failed, ())

    result = MultiPaperComparator().compare_batch(batch, ["results"])

    assert {cell.file_id for cell in result.matrix} == {"file-0", "file-1"}
