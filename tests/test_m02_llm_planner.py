from __future__ import annotations

import json

import pytest

from backend.agent_runtime.llm_planner import (
    ConstrainedLLMPlanner,
    PlannerContext,
    PlannerModelMetadata,
)
from backend.agent_runtime.planner import PlanBudget, RegistrySnapshot
from backend.models.client import ModelTokenUsage
from evaluation.m02_planner_evaluation import _report


def _valid_plan(tool: str = "search_document") -> str:
    return json.dumps(
        {
            "schema_version": "2.0",
            "plan_id": "generated-plan",
            "version": 1,
            "goal": "answer with evidence",
            "assumptions": [],
            "global_budget": {
                "max_tokens": 1000,
                "max_tool_calls": 2,
                "max_subagent_calls": 0,
                "max_duration_ms": 10000,
                "max_parallel_steps": 1,
            },
            "termination_condition": "answer is verified",
            "steps": [
                {
                    "step_id": "resolve-paper",
                    "action": "resolve paper",
                    "step_type": "skill",
                    "skill_name": "paper_comparison",
                    "depends_on": [],
                    "input_refs": ["requirement"],
                    "expected_output_schema": {"type": "object"},
                    "evidence_requirement": "optional",
                    "budget": {},
                    "risk": "low",
                    "completion_predicate": {
                        "kind": "sources_resolved",
                        "required_fields": ["paper_ids"],
                    },
                },
                {
                    "step_id": "retrieve",
                    "action": "retrieve evidence",
                    "step_type": "tool_call",
                    "tool_name": tool,
                    "depends_on": ["resolve-paper"],
                    "input_refs": ["requirement"],
                    "expected_output_schema": {"type": "object"},
                    "evidence_requirement": "required",
                    "budget": {
                        "max_tokens": 100,
                        "max_tool_calls": 1,
                        "max_subagent_calls": 0,
                        "timeout_ms": 1000,
                    },
                    "risk": "low",
                    "completion_predicate": {
                        "kind": "schema_and_evidence",
                        "required_fields": ["evidence"],
                        "minimum_evidence": 1,
                    },
                },
                {
                    "step_id": "answer-with-citations",
                    "action": "answer with citations",
                    "step_type": "generate",
                    "depends_on": ["retrieve"],
                    "input_refs": ["retrieve"],
                    "expected_output_schema": {"type": "object"},
                    "evidence_requirement": "required",
                    "budget": {"max_tokens": 500},
                    "risk": "low",
                    "completion_predicate": {
                        "kind": "answer_with_evidence",
                        "minimum_evidence": 1,
                    },
                },
            ],
        }
    )


class ScriptedLLM:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.prompts: list[str] = []
        self.last_usage = ModelTokenUsage(100, 50, 150)

    async def generate_with_schema(self, prompt: str, **_: object) -> str:
        self.prompts.append(prompt)
        return self.responses.pop(0)


def _context(*, difficulty: str = "L3") -> PlannerContext:
    return PlannerContext(
        requirement_brief="Compare methods with citations",
        difficulty=difficulty,
        candidate_skills=["paper_comparison"],
        allowed_tool_schemas={
            "search_document": {
                "description": "retrieve evidence",
                "input_schema": {"type": "object"},
            }
        },
        memory_summary="User prefers concise tables.",
        rag_summary="Two papers are available.",
        budget=PlanBudget(
            max_tokens=1000,
            max_tool_calls=2,
            max_subagent_calls=0,
            max_duration_ms=10_000,
        ),
    )


def _planner(llm: ScriptedLLM) -> ConstrainedLLMPlanner:
    return ConstrainedLLMPlanner(
        llm=llm,
        registry=RegistrySnapshot(
            skills={"paper_comparison"},
            tools={"search_document"},
            permitted_skills={"paper_comparison"},
            permitted_tools={"search_document"},
        ),
        model=PlannerModelMetadata(
            model="qwen3.5:4b",
            profile="planner-v2",
            version="base-v1",
            prompt_version="planner-prompt-v2",
        ),
    )


@pytest.mark.asyncio
async def test_simple_task_uses_fast_path_without_model_and_at_most_three_steps() -> None:
    llm = ScriptedLLM([])
    outcome = await _planner(llm).plan(_context(difficulty="L1"))
    assert outcome.trace.fast_path
    assert not llm.prompts
    assert len(outcome.plan.steps) <= 3


@pytest.mark.asyncio
async def test_invalid_generation_is_repaired_once_and_records_usage() -> None:
    llm = ScriptedLLM(["not json", _valid_plan()])
    outcome = await _planner(llm).plan(_context())
    assert len(llm.prompts) == 2
    assert outcome.trace.repair_attempted
    assert not outcome.trace.fallback_used
    assert outcome.trace.input_tokens == 200
    assert outcome.trace.output_tokens == 100
    assert outcome.trace.model == "qwen3.5:4b"
    assert "hidden reasoning" not in outcome.trace.model_dump_json()


@pytest.mark.asyncio
async def test_registry_or_schema_failure_falls_back_without_illegal_calls() -> None:
    llm = ScriptedLLM([_valid_plan("forbidden_tool"), _valid_plan("forbidden_tool")])
    outcome = await _planner(llm).plan(_context())
    assert outcome.trace.fallback_used
    assert outcome.trace.fallback_reason
    assert all(step.tool_name != "forbidden_tool" for step in outcome.plan.steps)
    assert {step.step_id for step in outcome.plan.steps} >= {
        "retrieve-evidence",
        "synthesize-answer",
        "verify-claims",
    }
    outcome.plan.validate_against(_planner(llm).registry)


@pytest.mark.asyncio
async def test_prompt_contains_only_top_k_allowed_capabilities() -> None:
    llm = ScriptedLLM([_valid_plan()])
    context = _context().model_copy(
        update={
            "candidate_skills": ["paper_comparison", "not_allowed"],
            "allowed_tool_schemas": {
                "search_document": {"description": "search"},
                "secret_tool": {"description": "must not leak"},
            },
        }
    )
    outcome = await _planner(llm).plan(context)
    assert not outcome.trace.fallback_used
    assert "paper_comparison" in llm.prompts[0]
    assert "search_document" in llm.prompts[0]
    assert "not_allowed" not in llm.prompts[0]
    assert "secret_tool" not in llm.prompts[0]
    prompt = json.loads(llm.prompts[0])
    assert prompt["required_workflow"] == [
        "resolve_sources",
        "retrieve_evidence",
        "answer_with_citations",
    ]


@pytest.mark.asyncio
async def test_semantically_incomplete_plan_is_repaired_then_safely_completed() -> None:
    incomplete = json.loads(_valid_plan())
    incomplete["steps"] = incomplete["steps"][1:2]
    llm = ScriptedLLM([json.dumps(incomplete), json.dumps(incomplete)])

    outcome = await _planner(llm).plan(_context())

    assert outcome.trace.repair_attempted
    assert outcome.trace.fallback_used
    action_text = " ".join(step.action.casefold() for step in outcome.plan.steps)
    assert "resolve paper" in action_text
    assert "retrieve evidence" in action_text
    assert "answer with citations" in action_text


def test_partial_complex_evaluation_report_allows_empty_simple_group() -> None:
    report = _report(
        [
            {
                "difficulty": "L5",
                "required_step_recall": 1.0,
                "b1_required_step_recall": 0.2,
                "generated_valid": False,
                "final_plan_valid": True,
                "registry_illegal_calls": 0,
                "step_count": 5,
                "fallback_used": True,
            }
        ]
    )
    assert report["simple_average_steps"] == 0.0
    assert report["gates"]["simple_average_steps_lte_3"]
