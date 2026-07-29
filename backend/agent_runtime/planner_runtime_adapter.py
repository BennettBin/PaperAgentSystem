"""Production adapter that turns the constrained Planner into public task state."""

from __future__ import annotations

from backend.agent_runtime.llm_planner import ConstrainedLLMPlanner, PlannerContext
from backend.agent_runtime.planner import PlanBudget
from backend.agent_runtime.unified import (
    PublicExecutionPlan,
    PublicPlanStep,
    RuntimeRequest,
)


class DynamicPlannerRuntimeAdapter:
    """Generate a bounded Plan while keeping prompts and hidden reasoning private."""

    def __init__(
        self,
        planner: ConstrainedLLMPlanner,
        *,
        skill_names: list[str],
        tool_schemas: dict[str, dict[str, object]],
    ) -> None:
        self._planner = planner
        self._skill_names = list(skill_names)
        self._tool_schemas = dict(tool_schemas)

    async def create_plan(self, request: RuntimeRequest) -> PublicExecutionPlan:
        candidate_skills = request.candidate_skills or self._skill_names[:10]
        outcome = await self._planner.plan(
            PlannerContext(
                requirement_brief=request.question,
                difficulty=_difficulty(request),
                candidate_skills=candidate_skills,
                allowed_tool_schemas=self._tool_schemas,
                budget=PlanBudget(
                    max_tokens=16_000,
                    max_tool_calls=8,
                    max_subagent_calls=0,
                    max_duration_ms=600_000,
                    max_parallel_steps=1,
                ),
            )
        )
        plan = outcome.plan
        return PublicExecutionPlan(
            plan_id=plan.plan_id,
            version=plan.version,
            goal=plan.goal,
            termination_condition=plan.termination_condition,
            steps=[
                PublicPlanStep(
                    step_id=step.step_id,
                    title=step.action,
                    step_type=(
                        step.step_type.value
                        if step.step_type is not None
                        else "generate"
                    ),
                    depends_on=list(step.depends_on),
                )
                for step in plan.steps
            ],
            fallback_used=outcome.trace.fallback_used,
            fallback_reason=outcome.trace.fallback_reason,
        )


def _difficulty(request: RuntimeRequest) -> str:
    normalized = request.question.casefold()
    if len(set(request.file_ids)) >= 2:
        return "L4"
    if any(
        marker in normalized
        for marker in (
            "比较",
            "综述",
            "综合",
            "冲突",
            "批判",
            "compare",
            "review",
            "synthesize",
        )
    ):
        return "L3"
    return "L3"
