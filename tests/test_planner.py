import pytest
from pydantic import ValidationError

from agent_runtime.planner import (
    ExecutionPlan,
    Planner,
    PlanStep,
    RegistrySnapshot,
)
from core.errors import ErrorCode, ProjectError


def registry() -> RegistrySnapshot:
    return RegistrySnapshot(
        skills={"paper_reader", "summary_generator"},
        tools={"parse_document", "verify_claim", "search_document"},
    )


def test_structured_plan_is_executable_and_has_completion_conditions() -> None:
    plan = Planner(registry()).create(
        goal="总结论文",
        skill_name="summary_generator",
        tool_names=["search_document", "verify_claim"],
    )

    assert len(plan.steps) <= 8
    assert all(step.completion_condition for step in plan.steps)
    assert plan.topological_order() == [step.step_id for step in plan.steps]


def test_plan_rejects_cycles_and_unknown_registry_entries() -> None:
    cyclic = ExecutionPlan(
        goal="x",
        steps=[
            PlanStep(step_id="a", action="x", skill_name="paper_reader", depends_on=["b"], completion_condition="a"),
            PlanStep(step_id="b", action="x", tool_name="parse_document", depends_on=["a"], completion_condition="b"),
        ],
    )
    with pytest.raises(ProjectError) as cycle:
        cyclic.validate_against(registry())
    assert cycle.value.code is ErrorCode.INVALID_ARGUMENT

    unknown = ExecutionPlan(
        goal="x",
        steps=[
            PlanStep(step_id="a", action="x", tool_name="not_registered", completion_condition="done"),
        ],
    )
    with pytest.raises(ProjectError) as missing:
        unknown.validate_against(registry())
    assert missing.value.code is ErrorCode.TOOL_NOT_FOUND


def test_plan_has_hard_eight_step_limit() -> None:
    with pytest.raises(ValidationError):
        ExecutionPlan(
            goal="too long",
            steps=[
                PlanStep(step_id=str(i), action="x", completion_condition="done")
                for i in range(9)
            ],
        )


def test_replanner_allows_at_most_two_replans() -> None:
    planner = Planner(registry())
    plan = planner.create("总结", "summary_generator", ["search_document"])
    plan = planner.replan(plan, failed_step_id="tool-1", reason="temporary")
    plan = planner.replan(plan, failed_step_id="tool-1", reason="temporary")

    with pytest.raises(ProjectError) as exc:
        planner.replan(plan, failed_step_id="tool-1", reason="again")

    assert exc.value.code is ErrorCode.RESOURCE_EXHAUSTED


def test_planner_evaluation_thresholds() -> None:
    planner = Planner(registry())
    plans = [
        planner.create("总结", "summary_generator", ["search_document", "verify_claim"])
        for _ in range(100)
    ]
    executable = sum(bool(plan.topological_order()) for plan in plans) / len(plans)
    dependency_correct = sum(
        plan.steps[-1].depends_on == [plan.steps[-2].step_id] for plan in plans
    ) / len(plans)
    unregistered_calls = sum(
        step.tool_name not in registry().tools
        for plan in plans
        for step in plan.steps
        if step.tool_name
    )

    assert executable >= 0.90
    assert dependency_correct >= 0.95
    assert unregistered_calls == 0
