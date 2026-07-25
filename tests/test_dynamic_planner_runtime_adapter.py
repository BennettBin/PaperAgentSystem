from __future__ import annotations

import pytest

from backend.agent_runtime.llm_planner import (
    ConstrainedLLMPlanner,
    PlannerModelMetadata,
)
from backend.agent_runtime.planner import RegistrySnapshot
from backend.agent_runtime.planner_runtime_adapter import (
    DynamicPlannerRuntimeAdapter,
)
from backend.agent_runtime.unified import RuntimeRequest


class InvalidPlannerLLM:
    async def generate_with_schema(
        self,
        prompt: str,
        system_prompt: str | None = None,
        response_schema: dict | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.0,
    ) -> str:
        return "{}"


@pytest.mark.asyncio
async def test_adapter_exposes_bounded_public_fallback_plan_without_reasoning() -> None:
    registry = RegistrySnapshot(
        skills={"paper_reader"},
        tools={"search_document"},
        permitted_skills={"paper_reader"},
        permitted_tools={"search_document"},
    )
    adapter = DynamicPlannerRuntimeAdapter(
        ConstrainedLLMPlanner(
            llm=InvalidPlannerLLM(),
            registry=registry,
            model=PlannerModelMetadata(
                model="small",
                profile="small",
                version="test",
                prompt_version="planner-v2",
            ),
        ),
        skill_names=["paper_reader"],
        tool_schemas={"search_document": {"type": "object"}},
    )

    plan = await adapter.create_plan(
        RuntimeRequest(
            task_id="task-1",
            question="总结这篇论文的方法并提供证据",
            file_ids=["paper-1"],
        )
    )

    assert 1 <= len(plan.steps) <= 8
    assert plan.fallback_used is True
    assert any(step.step_type == "tool_call" for step in plan.steps)
    serialized = plan.model_dump_json().casefold()
    assert "chain_of_thought" not in serialized
    assert "hidden_reasoning" not in serialized
