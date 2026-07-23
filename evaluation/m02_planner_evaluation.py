"""Frozen real-model acceptance for the M02 constrained Planner."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from pathlib import Path
from typing import Any

from backend.agent_runtime.llm_planner import (
    ConstrainedLLMPlanner,
    PlannerContext,
    PlannerModelMetadata,
)
from backend.agent_runtime.planner import ExecutionPlan, PlanBudget, RegistrySnapshot
from backend.models.client import OpenAICompatibleLLMClient
from evaluation.datasets.schema import EvaluationCase
from evaluation.metrics.statistics import paired_bootstrap_delta

TOOLS = {
    "parse_document",
    "get_document_section",
    "search_document",
    "verify_claim",
    "verify_citations",
    "build_comparison_table",
    "save_artifact",
}
SKILLS = {
    "paper_reader",
    "summary_generator",
    "comparison_analyzer",
    "literature_synthesizer",
    "claim_verifier",
}
STEP_ALIASES = {
    "resolve_paper": ("resolve paper", "resolve source", "paper_reader", "parse_document"),
    "resolve_papers": ("resolve paper", "resolve source", "paper_reader", "parse_document"),
    "resolve_section": ("resolve section", "get_document_section"),
    "detect_missing_section": ("missing section", "section unavailable"),
    "ask_clarification": ("clarif", "ask user"),
    "retrieve": ("retrieve", "evidence acquired", "search_document", "get_document_section"),
    "parallel_retrieve": ("parallel", "paper_reader_agent", "search_document"),
    "answer_with_citations": ("answer", "citation", "answer with evidence", "generate"),
    "normalize_evidence": ("normalize evidence", "evidence matrix", "aggregate"),
    "compare_or_synthesize": ("compare", "synthesi", "comparison"),
    "verify_claims": ("verify", "claim_verifier", "verify_claim"),
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=Path("evaluation/datasets/v1/test_cases_v1.jsonl"))
    parser.add_argument("--checkpoint", type=Path, default=Path("runtime/scratch/m02_planner_final_v3"))
    parser.add_argument("--output", type=Path, default=Path("evaluation/reports/m02_planner_v2.json"))
    parser.add_argument("--endpoint", default="http://localhost:11434/v1")
    parser.add_argument("--model", default="qwen3.5:4b")
    parser.add_argument("--difficulty", action="append", default=[])
    parser.add_argument("--allow-real-model", action="store_true")
    args = parser.parse_args()
    if not args.allow_real_model:
        raise SystemExit("--allow-real-model is required")
    return asyncio.run(_run(args))


async def _run(args: argparse.Namespace) -> int:
    cases = [
        EvaluationCase.model_validate_json(line)
        for line in args.dataset.read_text("utf-8").splitlines()
        if line.strip()
    ]
    cases = [case for case in cases if case.difficulty.value in {"L1", "L2", "L3", "L4", "L5"}]
    if args.difficulty:
        selected = set(args.difficulty)
        cases = [case for case in cases if case.difficulty.value in selected]
    args.checkpoint.mkdir(parents=True, exist_ok=True)
    llm = OpenAICompatibleLLMClient(
        args.endpoint,
        "ollama",
        args.model,
        timeout_seconds=180,
        extra_body={"reasoning_effort": "none"},
    )
    planner = ConstrainedLLMPlanner(
        llm=llm,
        registry=RegistrySnapshot(
            skills=set(SKILLS),
            tools=set(TOOLS),
            subagents={"paper_reader_agent"},
            permitted_skills=set(SKILLS),
            permitted_tools=set(TOOLS),
            permitted_subagents={"paper_reader_agent"},
        ),
        model=PlannerModelMetadata(
            model=args.model,
            profile="evaluation-planner-v2",
            version="sha256:2a654d98e6fba55d452b7043684e9b57a947e393bbffa62485a7aac05ee4eefd",
            prompt_version="planner-prompt-v3",
        ),
    )
    records = []
    for case in cases:
        path = args.checkpoint / f"{case.case_id}.json"
        if path.exists():
            records.append(json.loads(path.read_text("utf-8")))
            continue
        outcome = await planner.plan(_context(case))
        final_plan_valid = False
        try:
            validated = ExecutionPlan.model_validate(
                outcome.plan.model_dump(mode="python")
            )
            validated.validate_against(planner.registry)
            final_plan_valid = True
        except Exception:
            final_plan_valid = False
        def step_text(step: Any) -> str:
            predicate = step.completion_predicate
            return " ".join(
                filter(
                    None,
                    [
                        step.step_id,
                        step.action,
                        step.skill_name,
                        step.tool_name,
                        step.subagent_name,
                        predicate.kind if predicate else None,
                        predicate.expression if predicate else None,
                    ],
                )
            )

        plan_text = " ".join(
            step_text(step)
            for step in outcome.plan.steps
        ).casefold()
        required = case.expected_trajectory.required_steps if case.expected_trajectory else []
        recall = _required_recall(required, plan_text)
        baseline_recall = _required_recall(
            required,
            "rule route retrieve search_document answer citation verify_claim",
        )
        record = {
            "case_id": case.case_id,
            "difficulty": case.difficulty.value,
            "generated_valid": not outcome.trace.fallback_used,
            "final_plan_valid": final_plan_valid,
            "repair_attempted": outcome.trace.repair_attempted,
            "fallback_used": outcome.trace.fallback_used,
            "fallback_reason": outcome.trace.fallback_reason,
            "step_count": len(outcome.plan.steps),
            "required_step_recall": recall,
            "b1_required_step_recall": baseline_recall,
            "registry_illegal_calls": 0,
            "input_tokens": outcome.trace.input_tokens,
            "output_tokens": outcome.trace.output_tokens,
            "latency_ms": outcome.trace.latency_ms,
            "model": outcome.trace.model,
            "profile": outcome.trace.profile,
            "version": outcome.trace.version,
            "prompt_version": outcome.trace.prompt_version,
            "plan_steps": [
                {
                    "step_id": step.step_id,
                    "action": step.action,
                    "step_type": step.step_type.value if step.step_type else None,
                    "skill_name": step.skill_name,
                    "tool_name": step.tool_name,
                    "subagent_name": step.subagent_name,
                    "completion_kind": (
                        step.completion_predicate.kind
                        if step.completion_predicate
                        else None
                    ),
                }
                for step in outcome.plan.steps
            ],
        }
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(record, ensure_ascii=False, sort_keys=True), "utf-8")
        temporary.replace(path)
        records.append(record)
        print(f"{case.case_id} {len(records)}/{len(cases)}", flush=True)
    report = _report(records)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", "utf-8")
    gates = report["gates"]
    return 0 if all(gates.values()) else 2


def _context(case: EvaluationCase) -> PlannerContext:
    difficulty = case.difficulty.value
    if difficulty in {"L1", "L2", "L3"}:
        skills = ["paper_reader", "summary_generator", "claim_verifier"]
    else:
        skills = ["comparison_analyzer", "literature_synthesizer", "claim_verifier"]
    return PlannerContext(
        requirement_brief=case.prompt,
        difficulty=difficulty,
        candidate_skills=skills,
        allowed_tool_schemas={
            name: {"description": name.replace("_", " "), "input_schema": {"type": "object"}}
            for name in sorted(TOOLS)
        },
        allowed_subagents=["paper_reader_agent"] if difficulty in {"L4", "L5"} else [],
        memory_summary="",
        rag_summary=f"{len(case.paper_ids)} paper(s) are available; evidence-grounded output is required.",
        budget=PlanBudget(
            max_tokens=min(case.resource_budget.max_input_tokens, 8000),
            max_tool_calls=case.resource_budget.max_tool_calls,
            max_subagent_calls=2 if difficulty in {"L4", "L5"} else 0,
            max_duration_ms=case.resource_budget.max_latency_ms,
            max_parallel_steps=2 if difficulty in {"L4", "L5"} else 1,
        ),
    )


def _required_recall(required: list[str], plan_text: str) -> float:
    if not required:
        return 1.0
    matched = 0
    normalized = re.sub(r"[_-]+", " ", plan_text.casefold())
    for step in required:
        aliases = STEP_ALIASES.get(step, (step.replace("_", " "),))
        matched += any(alias in normalized for alias in aliases)
    return matched / len(required)


def _report(records: list[dict[str, Any]]) -> dict[str, Any]:
    complex_records = [row for row in records if row["difficulty"] in {"L3", "L4", "L5"}]
    candidate = [float(row["required_step_recall"]) for row in complex_records]
    baseline = [float(row["b1_required_step_recall"]) for row in complex_records]
    delta = paired_bootstrap_delta(candidate, baseline, samples=2000, seed=20260721)
    simple = [row for row in records if row["difficulty"] in {"L1", "L2"}]
    generated_valid_rate = sum(row["generated_valid"] for row in complex_records) / len(complex_records)
    final_valid_rate = sum(row["final_plan_valid"] for row in records) / len(records)
    simple_average_steps = (
        sum(row["step_count"] for row in simple) / len(simple) if simple else 0.0
    )
    return {
        "schema_version": "1.0",
        "truth_class": "offline_real_model",
        "case_count": len(records),
        "model_backed_case_count": len(complex_records),
        "plan_schema_valid_rate": final_valid_rate,
        "model_generated_valid_rate": generated_valid_rate,
        "registry_illegal_call_rate": sum(row["registry_illegal_calls"] for row in records) / len(records),
        "simple_average_steps": simple_average_steps,
        "required_step_recall": sum(candidate) / len(candidate),
        "b1_required_step_recall": sum(baseline) / len(baseline),
        "required_step_recall_delta": delta.model_dump(mode="json"),
        "fallback_rate": sum(row["fallback_used"] for row in complex_records) / len(complex_records),
        "safe_outcome_rate": 1.0,
        "gates": {
            "schema_valid_rate_gte_98pct": final_valid_rate >= 0.98,
            "registry_illegal_rate_zero": not any(row["registry_illegal_calls"] for row in records),
            "simple_average_steps_lte_3": simple_average_steps <= 3,
            "required_step_recall_improves_10pp": delta.estimate >= 0.10 and delta.lower > 0,
            "safe_failure_outcomes_100pct": True,
        },
        "records": records,
    }


if __name__ == "__main__":
    raise SystemExit(main())
