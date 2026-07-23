from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from backend.agent_runtime.planner import (
    CompletionPredicate,
    ExecutionPlan,
    Observation,
    ObservationStatus,
    PlanBudget,
    PlanPatch,
    PlanPatchOperation,
    PlanStep,
    RegistrySnapshot,
    StepBudget,
    StepType,
    migrate_plan_v1,
)
from backend.core.errors import ProjectError

REGISTRY = RegistrySnapshot(
    skills={"paper_reader"},
    tools={"search_document", "verify_claims"},
    subagents={"paper_reader_agent"},
)


def _step(step_id: str = "s1", **updates: object) -> PlanStep:
    values: dict[str, object] = {
        "step_id": step_id,
        "action": "search evidence",
        "step_type": StepType.TOOL_CALL,
        "tool_name": "search_document",
        "expected_output_schema": {"type": "object"},
        "evidence_requirement": "required",
        "budget": StepBudget(max_tokens=100, max_tool_calls=1, timeout_ms=1000),
        "risk": "low",
        "completion_predicate": CompletionPredicate(
            kind="schema_and_evidence",
            required_fields=["evidence"],
            minimum_evidence=1,
        ),
    }
    values.update(updates)
    return PlanStep(**values)


def _plan(*steps: PlanStep) -> ExecutionPlan:
    return ExecutionPlan(
        plan_id="plan-1",
        version=1,
        goal="answer with evidence",
        assumptions=["paper is available"],
        global_budget=PlanBudget(
            max_tokens=1000,
            max_tool_calls=4,
            max_subagent_calls=1,
            max_duration_ms=10_000,
        ),
        termination_condition="all required claims are supported",
        steps=list(steps) or [_step()],
    )


def test_plan_v2_validates_registry_dag_budget_and_completion() -> None:
    plan = _plan(
        _step(),
        _step(
            "s2",
            action="verify",
            tool_name="verify_claims",
            depends_on=["s1"],
        ),
    )
    plan.validate_against(REGISTRY)
    assert plan.topological_order() == ["s1", "s2"]

    with pytest.raises(ProjectError, match="budget"):
        _plan(_step(budget=StepBudget(max_tokens=1001))).validate_against(REGISTRY)
    with pytest.raises(ProjectError, match="Unregistered Tool"):
        _plan(_step(tool_name="unknown")).validate_against(REGISTRY)
    with pytest.raises(ProjectError, match="cycle"):
        _plan(_step("a", depends_on=["b"]), _step("b", depends_on=["a"])).validate_against(REGISTRY)
    with pytest.raises(ValidationError):
        _step(completion_predicate=None, completion_condition="")


def test_v1_plan_migrates_without_losing_execution_semantics() -> None:
    legacy = {
        "goal": "legacy goal",
        "steps": [
            {
                "step_id": "tool-1",
                "action": "search",
                "tool_name": "search_document",
                "depends_on": [],
                "completion_condition": "valid result returned",
            }
        ],
        "replan_count": 1,
    }
    migrated = migrate_plan_v1(legacy, plan_id="legacy-plan")
    migrated.validate_against(REGISTRY)
    assert migrated.schema_version == "2.0"
    assert migrated.plan_id == "legacy-plan"
    assert migrated.replan_count == 1
    assert migrated.steps[0].completion_predicate.kind == "legacy_condition"


def test_plan_patch_creates_new_version_and_trace_diff_without_mutation() -> None:
    original = _plan()
    snapshot = deepcopy(original.model_dump(mode="json"))
    trigger = Observation(
        step_id="s1",
        status=ObservationStatus.REPAIR,
        error_code="insufficient_evidence",
        retryable=True,
        quality_signal={"evidence_coverage": 0.0},
    )
    patch = PlanPatch(
        patch_id="patch-1",
        base_plan_id=original.plan_id,
        base_version=original.version,
        reason_summary="Acquire more evidence",
        trigger_observation=trigger,
        operations=[
            PlanPatchOperation(
                operation="update",
                step_id="s1",
                changes={"action": "rewrite query and search evidence"},
            )
        ],
    )
    revised, trace = patch.apply(original, REGISTRY)
    assert original.model_dump(mode="json") == snapshot
    assert revised.version == 2
    assert revised.parent_plan_id == original.plan_id
    assert revised.steps[0].action == "rewrite query and search evidence"
    assert trace.from_version == 1 and trace.to_version == 2
    assert trace.trigger_observation.error_code == "insufficient_evidence"


def test_one_hundred_schema_fixtures_are_classified_exactly() -> None:
    fixtures: list[tuple[dict, bool]] = []
    for index in range(50):
        fixtures.append(
            (
                _plan(_step(f"valid-{index}")).model_dump(mode="python"),
                True,
            )
        )
    for index in range(50):
        invalid = _plan(_step(f"invalid-{index}")).model_dump(mode="python")
        if index % 5 == 0:
            invalid["termination_condition"] = ""
        elif index % 5 == 1:
            invalid["steps"][0]["completion_predicate"] = None
            invalid["steps"][0]["completion_condition"] = ""
        elif index % 5 == 2:
            invalid["steps"][0]["depends_on"] = ["missing"]
        elif index % 5 == 3:
            invalid["steps"][0]["tool_name"] = "unknown"
        else:
            invalid["steps"][0]["budget"]["max_tokens"] = 1001
        fixtures.append((invalid, False))

    predictions = []
    for payload, expected in fixtures:
        try:
            plan = ExecutionPlan.model_validate(payload)
            plan.validate_against(REGISTRY)
            actual = True
        except (ValidationError, ProjectError):
            actual = False
        predictions.append(actual == expected)
    assert len(predictions) == 100
    assert all(predictions)
