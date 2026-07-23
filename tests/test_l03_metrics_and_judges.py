from __future__ import annotations

import json
from pathlib import Path

import pytest

from evaluation.datasets.audit import load_cases
from evaluation.datasets.schema import JudgeResult, JudgeType, JudgeVerdict
from evaluation.judges.system import (
    JudgeContractError,
    JudgeInput,
    JudgeSystem,
    ProgrammaticJudge,
)
from evaluation.metrics.catalog import CORE_METRICS, MetricName
from evaluation.metrics.engine import CaseMetricRecord, MetricsEngine
from evaluation.metrics.statistics import bootstrap_mean_ci, paired_bootstrap_delta

ROOT = Path(__file__).resolve().parents[1]
DATASET_ROOT = ROOT / "evaluation" / "datasets" / "v1"


class SpyJudge:
    def __init__(self, result: JudgeResult) -> None:
        self.result = result
        self.calls = 0

    def judge(self, judge_input: JudgeInput) -> JudgeResult:
        self.calls += 1
        return self.result


class AlternatingJudge:
    def __init__(self, results: list[JudgeResult]) -> None:
        self._results = results
        self.calls = 0

    def judge(self, judge_input: JudgeInput) -> JudgeResult:
        result = self._results[self.calls % len(self._results)]
        self.calls += 1
        return result


def _case():
    return next(
        case
        for case in load_cases(DATASET_ROOT / "test_cases_v1.jsonl")
        if case.requires_evidence
        and case.reference_answer is not None
        and case.reference_answer.answer.casefold().strip(". ") not in {"yes", "no"}
    )


def _record(case_id: str, *, success: bool, correctness: float, latency_ms: float) -> CaseMetricRecord:
    return CaseMetricRecord(
        case_id=case_id,
        task_success=success,
        answer_correctness=correctness,
        citation_true_positive=2 if success else 1,
        citation_false_positive=0 if success else 1,
        citation_false_negative=0 if success else 1,
        supported_claims=2 if success else 1,
        total_claims=2,
        hallucinated_claims=0 if success else 1,
        intent_rank=1 if success else 4,
        skill_rank=1 if success else 2,
        expected_tools=["retrieve"],
        selected_tools=["retrieve"] if success else ["web_search"],
        argument_exact=success,
        argument_schema_valid=True,
        plan_valid=success,
        required_steps_matched=3 if success else 2,
        required_steps_total=3,
        invalid_steps=0 if success else 1,
        total_steps=3,
        successful_tool_calls=2 if success else 1,
        total_tool_calls=2,
        replan_attempted=not success,
        replan_succeeded=False if not success else None,
        loop_detected=False,
        model_calls=2,
        tool_calls=2,
        input_tokens=1000,
        output_tokens=200,
        latency_ms=latency_ms,
        four_b_calls=1,
        total_model_calls=2,
        gpu_seconds=1.5,
        monetary_cost=0.0,
        recovery_attempted=not success,
        recovery_succeeded=False if not success else None,
        partial_failure_case=not success,
        partial_result_usable=False if not success else None,
        cancellation_case=False,
        cancellation_response_ms=None,
        prompt_injection_case=False,
        prompt_injection_blocked=None,
    )


def test_metric_catalog_documents_formula_denominator_scope_and_outliers() -> None:
    required = {
        MetricName.TASK_SUCCESS,
        MetricName.ANSWER_CORRECTNESS,
        MetricName.CITATION_PRECISION,
        MetricName.CITATION_RECALL,
        MetricName.CLAIM_SUPPORT_RATE,
        MetricName.HALLUCINATION_RATE,
        MetricName.INTENT_TOP1,
        MetricName.INTENT_TOP3,
        MetricName.SKILL_TOP1,
        MetricName.SKILL_TOP3,
        MetricName.TOOL_SELECTION_F1,
        MetricName.ARGUMENT_EXACT_RATE,
        MetricName.ARGUMENT_SCHEMA_VALID_RATE,
        MetricName.PLAN_VALIDITY,
        MetricName.REQUIRED_STEP_RECALL,
        MetricName.INVALID_STEP_RATE,
        MetricName.TOOL_SUCCESS_RATE,
        MetricName.REPLAN_SUCCESS_RATE,
        MetricName.LOOP_RATE,
        MetricName.MODEL_CALLS,
        MetricName.TOOL_CALLS,
        MetricName.INPUT_TOKENS,
        MetricName.OUTPUT_TOKENS,
        MetricName.LATENCY_P50_MS,
        MetricName.LATENCY_P95_MS,
        MetricName.TOKENS_PER_SUCCESS,
        MetricName.FOUR_B_CALL_RATE,
        MetricName.GPU_SECONDS,
        MetricName.MONETARY_COST,
        MetricName.FAILURE_RECOVERY_RATE,
        MetricName.PARTIAL_FAILURE_USABILITY,
        MetricName.CANCELLATION_RESPONSE_MS,
        MetricName.PROMPT_INJECTION_BLOCK_RATE,
    }
    assert required <= set(CORE_METRICS)
    assert all(definition.formula for definition in CORE_METRICS.values())
    assert all(definition.denominator for definition in CORE_METRICS.values())
    assert all(definition.applicability for definition in CORE_METRICS.values())
    assert all(definition.outlier_handling for definition in CORE_METRICS.values())


def test_metrics_report_keeps_schema_validity_separate_from_task_correctness() -> None:
    records = [
        _record("case-a", success=True, correctness=1.0, latency_ms=100),
        _record("case-b", success=False, correctness=0.0, latency_ms=300),
    ]
    report = MetricsEngine(seed=7, bootstrap_samples=300).compute(records)

    assert report.metrics[MetricName.TASK_SUCCESS].value == 0.5
    assert report.metrics[MetricName.ARGUMENT_SCHEMA_VALID_RATE].value == 1.0
    assert report.metrics[MetricName.TASK_SUCCESS].value != report.metrics[
        MetricName.ARGUMENT_SCHEMA_VALID_RATE
    ].value
    assert report.metrics[MetricName.LATENCY_P50_MS].value == 200
    assert report.metrics[MetricName.LATENCY_P95_MS].value == 290


def test_comparison_report_contains_absolute_delta_and_95_percent_ci() -> None:
    baseline = [
        _record("case-a", success=False, correctness=0.0, latency_ms=300),
        _record("case-b", success=False, correctness=0.0, latency_ms=400),
    ]
    candidate = [
        _record("case-a", success=True, correctness=1.0, latency_ms=100),
        _record("case-b", success=False, correctness=0.0, latency_ms=300),
    ]

    comparison = MetricsEngine(seed=11, bootstrap_samples=300).compare(
        candidate, baseline, baseline_id="b0", candidate_id="candidate"
    )
    metric = comparison.metrics[MetricName.TASK_SUCCESS]

    assert metric.absolute == 0.5
    assert metric.baseline == 0.0
    assert metric.delta == 0.5
    assert metric.absolute_ci.confidence == 0.95
    assert metric.delta_ci.confidence == 0.95


def test_bootstrap_and_paired_bootstrap_are_seeded_and_deterministic() -> None:
    first = bootstrap_mean_ci([0.0, 1.0, 1.0, 0.0], samples=500, seed=17)
    second = bootstrap_mean_ci([0.0, 1.0, 1.0, 0.0], samples=500, seed=17)
    delta = paired_bootstrap_delta(
        [1.0, 1.0, 0.0], [0.0, 1.0, 0.0], samples=500, seed=19
    )

    assert first == second
    assert first.lower <= 0.5 <= first.upper
    assert delta.estimate == pytest.approx(1 / 3)
    assert delta.confidence == 0.95


def test_programmatic_judge_precedes_llm_and_returns_structured_evidence() -> None:
    case = _case()
    llm = SpyJudge(
        JudgeResult(
            case_id=case.case_id,
            judge_type=JudgeType.LLM,
            verdict=JudgeVerdict.FAIL,
            reason_summary="LLM should not be called for an exact rule match.",
            evidence_ids=[],
            judge_profile="judge-4b",
            judge_version="judge-v1",
        )
    )
    system = JudgeSystem(programmatic=ProgrammaticJudge(), llm_judge=llm)
    result = system.judge(
        JudgeInput(
            case=case,
            candidate_answer=case.reference_answer.answer,
            candidate_evidence_ids=[item.evidence_id for item in case.required_evidence],
        )
    )

    assert result.verdict is JudgeVerdict.PASS
    assert result.judge_type is JudgeType.PROGRAMMATIC
    assert result.reason_summary
    assert result.evidence_ids
    assert llm.calls == 0


def test_llm_judge_unknown_evidence_fails_closed() -> None:
    case = _case()
    llm = SpyJudge(
        JudgeResult(
            case_id=case.case_id,
            judge_type=JudgeType.LLM,
            verdict=JudgeVerdict.PASS,
            reason_summary="Claims support from an unknown citation.",
            evidence_ids=["not-a-gold-evidence-id"],
            judge_profile="judge-4b",
            judge_version="judge-v1",
        )
    )
    system = JudgeSystem(programmatic=ProgrammaticJudge(), llm_judge=llm)

    with pytest.raises(JudgeContractError, match="unknown evidence"):
        system.judge(
            JudgeInput(
                case=case,
                candidate_answer="A partially overlapping answer that rules abstain on.",
                candidate_evidence_ids=[item.evidence_id for item in case.required_evidence],
            )
        )


def test_unstable_llm_judge_uses_human_fallback() -> None:
    case = _case()
    evidence_ids = [item.evidence_id for item in case.required_evidence]
    llm = AlternatingJudge(
        [
            JudgeResult(
                case_id=case.case_id,
                judge_type=JudgeType.LLM,
                verdict=verdict,
                reason_summary=f"Structured LLM verdict {verdict.value}.",
                evidence_ids=evidence_ids,
                judge_profile="judge-4b",
                judge_version="judge-v1",
            )
            for verdict in (JudgeVerdict.PASS, JudgeVerdict.FAIL)
        ]
    )
    human = SpyJudge(
        JudgeResult(
            case_id=case.case_id,
            judge_type=JudgeType.HUMAN,
            verdict=JudgeVerdict.PASS,
            reason_summary="Human reviewer resolves the unstable semantic judgment.",
            evidence_ids=evidence_ids,
            judge_version="human-rubric-v1",
        )
    )
    system = JudgeSystem(
        programmatic=ProgrammaticJudge(), llm_judge=llm, human_judge=human
    )

    repeated = system.judge_repeated(
        JudgeInput(
            case=case,
            candidate_answer="A semantic paraphrase requiring supplemental judgment.",
            candidate_evidence_ids=evidence_ids,
        ),
        repetitions=3,
    )

    assert repeated.consistency == pytest.approx(2 / 3)
    assert repeated.used_human_fallback
    assert repeated.final_result.judge_type is JudgeType.HUMAN
    assert human.calls == 1


def test_l03_calibration_uses_50_human_reference_gold_cases() -> None:
    report = json.loads(
        (ROOT / "evaluation" / "reports" / "l03_judge_calibration.json").read_text(
            encoding="utf-8"
        )
    )

    assert report["case_count"] == 50
    assert report["human_reference_gold_count"] == 50
    assert report["controlled_negative_count"] == 25
    assert report["truth_class"] == "integration_real"
    assert report["gold_truth_class"] == "human_review"
    assert report["agreement_rate"] >= 0.90
    assert report["three_run_consistency_rate"] >= 0.95
    assert all(item["reason_summary"] for item in report["results"])
