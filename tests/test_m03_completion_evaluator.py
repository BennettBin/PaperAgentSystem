from __future__ import annotations

from backend.agent_runtime.completion_evaluator import (
    ClaimEvidence,
    CompletionEvaluationInput,
    CompletionEvaluator,
    EvidenceRecord,
    NumericCheck,
)
from backend.agent_runtime.planner import (
    CompletionPredicate,
    EvidenceRequirement,
    ObservationStatus,
    PlanStep,
    StepType,
)


def _step(
    kind: str,
    *,
    action: str = "answer with citations",
    step_type: StepType = StepType.GENERATE,
    required_fields: list[str] | None = None,
    minimum_evidence: int = 0,
) -> PlanStep:
    return PlanStep(
        step_id="quality-step",
        action=action,
        step_type=step_type,
        evidence_requirement=(
            EvidenceRequirement.REQUIRED
            if minimum_evidence
            else EvidenceRequirement.NONE
        ),
        completion_predicate=CompletionPredicate(
            kind=kind,
            required_fields=required_fields or [],
            minimum_evidence=minimum_evidence,
        ),
    )


def _evidence(
    evidence_id: str = "E1",
    *,
    source_id: str = "paper-a",
    page_number: int | None = 1,
    claim_id: str = "C1",
) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=evidence_id,
        source_id=source_id,
        page_number=page_number,
        claim_ids=[claim_id],
    )


def test_supported_citation_result_is_complete_and_writes_quality_signal() -> None:
    result = CompletionEvaluator().evaluate(
        _step("answer_with_evidence", required_fields=["answer"], minimum_evidence=1),
        CompletionEvaluationInput(
            output={"answer": "Supported result [E1]"},
            claims=[ClaimEvidence(claim_id="C1", text="Supported result", evidence_ids=["E1"])],
            evidence=[_evidence()],
        ),
    )
    assert result.decision is ObservationStatus.COMPLETE
    assert result.observation.status is ObservationStatus.COMPLETE
    assert result.observation.evidence_refs == ["E1"]
    assert result.observation.quality_signal["claim_evidence_coverage"] == 1.0


def test_unsupported_factual_claim_can_never_be_complete() -> None:
    result = CompletionEvaluator().evaluate(
        _step("answer_with_evidence", minimum_evidence=1),
        CompletionEvaluationInput(
            output={"answer": "Unsupported fact"},
            claims=[ClaimEvidence(claim_id="C1", text="Unsupported fact")],
        ),
    )
    assert result.decision is ObservationStatus.REPAIR
    assert "claim:C1:missing_evidence" in result.missing_items


def test_comparison_and_writing_checks_report_specific_missing_items() -> None:
    comparison = CompletionEvaluator().evaluate(
        _step(
            "comparison_complete",
            action="compare papers",
            step_type=StepType.AGGREGATE,
            required_fields=["method", "result"],
            minimum_evidence=1,
        ),
        CompletionEvaluationInput(
            output={"method": "A"},
            evidence=[_evidence()],
            target_paper_ids=["paper-a", "paper-b"],
            numeric_checks=[
                NumericCheck(claim_id="C-number", value="95%", verified=False)
            ],
        ),
    )
    assert "field:result" in comparison.missing_items
    assert "paper:paper-b" in comparison.missing_items
    assert "numeric_claim:C-number" in comparison.missing_items

    writing = CompletionEvaluator().evaluate(
        _step("writing_complete", action="write evidence-grounded draft"),
        CompletionEvaluationInput(
            output={"draft": "A draft", "evidence_map": {}},
            claims=[ClaimEvidence(claim_id="C1", text="Fact", evidence_ids=["E1"])],
            evidence=[_evidence()],
            immutable_terms=["QASPER"],
            review_required=True,
        ),
    )
    assert "evidence_map:C1" in writing.missing_items
    assert "immutable_term:QASPER" in writing.missing_items
    assert "pending_review" in writing.missing_items


def test_decision_escalates_from_repair_to_replan_ask_user_or_fail() -> None:
    step = _step("schema_complete", required_fields=["answer"])
    evaluator = CompletionEvaluator()
    assert evaluator.evaluate(
        step, CompletionEvaluationInput(output={}, repair_attempts=2)
    ).decision is ObservationStatus.REPLAN
    assert evaluator.evaluate(
        step, CompletionEvaluationInput(output={}, requires_user_input=True)
    ).decision is ObservationStatus.ASK_USER
    assert evaluator.evaluate(
        step, CompletionEvaluationInput(output={}, fatal_error="unsafe output")
    ).decision is ObservationStatus.FAIL


def test_fifty_tool_success_but_bad_gold_fixtures_have_under_five_percent_miss_rate() -> None:
    evaluator = CompletionEvaluator()
    fixtures: list[tuple[PlanStep, CompletionEvaluationInput, ObservationStatus]] = []
    for index in range(10):
        fixtures.append(
            (
                _step("answer_with_evidence", minimum_evidence=1),
                CompletionEvaluationInput(
                    output={"answer": f"unsupported {index}"},
                    claims=[ClaimEvidence(claim_id=f"C{index}", text="fact")],
                ),
                ObservationStatus.REPAIR,
            )
        )
    for index in range(10):
        fixtures.append(
            (
                _step("answer_with_evidence", minimum_evidence=1),
                CompletionEvaluationInput(
                    output={"answer": "bad provenance"},
                    claims=[ClaimEvidence(claim_id="C1", text="fact", evidence_ids=[f"E{index}"])],
                    evidence=[_evidence(f"E{index}", page_number=None)],
                ),
                ObservationStatus.REPAIR,
            )
        )
    for index in range(10):
        fixtures.append(
            (
                _step(
                    "comparison_complete",
                    action="compare papers",
                    step_type=StepType.AGGREGATE,
                    required_fields=["method", "result"],
                    minimum_evidence=1,
                ),
                CompletionEvaluationInput(
                    output={"method": f"method-{index}"},
                    evidence=[_evidence(source_id="paper-a")],
                    target_paper_ids=["paper-a", "paper-b"],
                ),
                ObservationStatus.REPAIR,
            )
        )
    for index in range(10):
        fixtures.append(
            (
                _step("writing_complete", action="write evidence-grounded draft"),
                CompletionEvaluationInput(
                    output={"draft": f"draft-{index}", "evidence_map": {}},
                    claims=[ClaimEvidence(claim_id="C1", text="fact", evidence_ids=["E1"])],
                    evidence=[_evidence()],
                    immutable_terms=["QASPER"],
                    review_required=True,
                ),
                ObservationStatus.REPAIR,
            )
        )
    for index in range(5):
        fixtures.append(
            (
                _step("schema_complete", required_fields=["answer"]),
                CompletionEvaluationInput(output={}, requires_user_input=True),
                ObservationStatus.ASK_USER,
            )
        )
        fixtures.append(
            (
                _step("schema_complete", required_fields=["answer"]),
                CompletionEvaluationInput(output={}, repair_attempts=2),
                ObservationStatus.REPLAN,
            )
        )

    assert len(fixtures) == 50
    predictions = [evaluator.evaluate(step, item) for step, item, _ in fixtures]
    false_completes = sum(item.decision is ObservationStatus.COMPLETE for item in predictions)
    agreements = sum(
        result.decision is gold
        for result, (_, _, gold) in zip(predictions, fixtures, strict=True)
    )
    assert false_completes / len(fixtures) < 0.05
    assert agreements / len(fixtures) >= 0.90
    assert all(result.missing_items for result in predictions)
