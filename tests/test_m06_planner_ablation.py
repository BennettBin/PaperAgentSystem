from __future__ import annotations

import json
from pathlib import Path

from evaluation.baseline_evaluation import InMemoryHybridRetriever, PageRecord, RealModelGateway
from evaluation.datasets.schema import EvaluationCase
from evaluation.experiments import ExperimentCase
from evaluation.m06_planner_ablation import (
    PlannerAblationExecutor,
    PlannerAblationKind,
    build_m06_report,
)


class ScriptedGateway(RealModelGateway):
    def __init__(self, responses: list[dict[str, object]]) -> None:
        self.responses = list(responses)
        self.prompts: list[str] = []

    def complete(
        self, *, model: str, profile: str, prompt: str, max_tokens: int
    ) -> tuple[str, int, int, int]:
        self.prompts.append(prompt)
        return json.dumps(self.responses.pop(0)), 100, 20, 5


def _case() -> EvaluationCase:
    path = Path("evaluation/datasets/v1/test_cases_v1.jsonl")
    return next(
        EvaluationCase.model_validate_json(line)
        for line in path.read_text("utf-8").splitlines()
        if '"case_id": "l3-001"' in line
    )


def test_full_ablation_replans_without_gold_in_control_prompt_and_recovers() -> None:
    case = _case()
    gold = case.required_evidence[0]
    gateway = ScriptedGateway(
        [
            {"tool": "hybrid_retrieval", "queries": [case.prompt]},
            {"answer": "unsupported", "citations": []},
            {"supported": False, "needs_more_evidence": True, "query": case.prompt},
            {
                "answer": case.reference_answer.answer,
                "citations": ["E1"],
            },
        ]
    )
    executor = PlannerAblationExecutor(
        kind=PlannerAblationKind.PLAN_COMPLETION_REPLAN,
        gateway=gateway,
        retriever=InMemoryHybridRetriever(
            [
                PageRecord(
                    paper_id=gold.paper_id,
                    page_number=gold.page_number,
                    section=gold.section,
                    text=gold.span_text,
                )
            ]
        ),
        model="qwen3.5:4b",
        model_version="sha256:test",
    )
    result = executor.execute(
        ExperimentCase(case_id=case.case_id, payload=case.model_dump(mode="json")),
        seed=1,
        attempt=1,
    )
    assert result.passed
    assert result.output["replan_count"] == 1
    assert result.output["invalid_tool_calls"] == 0
    assert any(event.kind == "plan" and event.data["version"] == 2 for event in result.trace)
    control_prompts = gateway.prompts[:-1]
    assert all("reference_answer" not in prompt for prompt in control_prompts)
    assert all("required_evidence" not in prompt for prompt in control_prompts)


def test_m06_report_applies_all_promotion_gates_without_hiding_failures() -> None:
    rows = []
    for index in range(20):
        rows.extend(
            [
                {
                    "case_id": f"c{index}",
                    "system_id": "fixed_workflow",
                    "difficulty": "L3",
                    "task_success": index < 2,
                    "total_tokens": 100,
                    "invalid_tool_calls": 1 if index < 4 else 0,
                    "tool_calls": 1,
                    "recovery_attempted": index < 10,
                    "recovery_succeeded": index < 2,
                    "looped": False,
                    "severe_unauthorized_calls": 0,
                },
                {
                    "case_id": f"c{index}",
                    "system_id": "plan_completion_replan",
                    "difficulty": "L3",
                    "task_success": index < 6,
                    "total_tokens": 110,
                    "invalid_tool_calls": 0,
                    "tool_calls": 1,
                    "recovery_attempted": index < 10,
                    "recovery_succeeded": index < 6,
                    "looped": False,
                    "severe_unauthorized_calls": 0,
                },
            ]
        )
    report = build_m06_report(rows, truth_class="unit_fixture")
    assert report["gates"]["l3_l5_success_improves_8pp"]
    assert report["gates"]["invalid_tool_call_rate_reduces_25pct"]
    assert report["gates"]["fault_recovery_improves_15pp"]
    assert report["gates"]["token_per_success_increase_lte_15pct"]
    assert report["gates"]["zero_loops_and_unauthorized_calls"]
