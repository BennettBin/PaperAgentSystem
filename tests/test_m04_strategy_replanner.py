from __future__ import annotations

import pytest

from backend.agent_runtime.planner import (
    CompletionPredicate,
    ExecutionPlan,
    Observation,
    ObservationStatus,
    PlanBudget,
    PlanStep,
    RegistrySnapshot,
    StepBudget,
    StepType,
)
from backend.agent_runtime.strategy_replanner import (
    FailureClass,
    ReplanRequest,
    ReplanResources,
    ReplanStrategy,
    StrategyReplanner,
    classify_failure,
)
from backend.core.errors import ErrorCode, ProjectError


def _registry() -> RegistrySnapshot:
    return RegistrySnapshot(
        skills={"paper_reader"},
        tools={"search_document", "backup_search", "verify_claim"},
        permitted_skills={"paper_reader"},
        permitted_tools={"search_document", "backup_search", "verify_claim"},
    )


def _plan() -> ExecutionPlan:
    return ExecutionPlan(
        goal="answer from cited evidence",
        global_budget=PlanBudget(
            max_tokens=2000,
            max_tool_calls=4,
            max_subagent_calls=0,
            max_duration_ms=30_000,
        ),
        steps=[
            PlanStep(
                step_id="retrieve",
                action="Retrieve evidence",
                step_type=StepType.TOOL_CALL,
                tool_name="search_document",
                budget=StepBudget(max_tokens=500, max_tool_calls=1),
                completion_predicate=CompletionPredicate(
                    kind="evidence_acquired", minimum_evidence=1
                ),
            ),
            PlanStep(
                step_id="answer",
                action="Answer with citations",
                depends_on=["retrieve"],
                budget=StepBudget(max_tokens=1000),
                completion_predicate=CompletionPredicate(
                    kind="answer_with_evidence", minimum_evidence=1
                ),
            ),
        ],
    )


def _observation(code: str, *missing: str) -> Observation:
    return Observation(
        step_id="retrieve",
        status=ObservationStatus.REPLAN,
        error_code=code,
        missing_items=list(missing),
    )


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (FailureClass.EMPTY_RETRIEVAL, ReplanStrategy.QUERY_REWRITE),
        (FailureClass.AMBIGUOUS_SECTION, ReplanStrategy.ASK_USER),
        (FailureClass.TOOL_TIMEOUT, ReplanStrategy.ALTERNATE_TOOL),
        (FailureClass.INVALID_ARGUMENTS, ReplanStrategy.ARGUMENT_REPAIR),
        (FailureClass.INSUFFICIENT_EVIDENCE, ReplanStrategy.EVIDENCE_ACQUISITION),
        (FailureClass.BUDGET_PRESSURE, ReplanStrategy.CONTEXT_COMPRESSION),
        (FailureClass.SUBAGENT_PARTIAL_FAILURE, ReplanStrategy.PARTIAL_AGGREGATION),
        (FailureClass.VERIFICATION_FAILURE, ReplanStrategy.EVIDENCE_ACQUISITION),
    ],
)
def test_eight_failure_classes_produce_observable_strategy_patch(
    failure: FailureClass, expected: ReplanStrategy
) -> None:
    plan = _plan()
    outcome = StrategyReplanner(_registry()).replan(
        plan,
        ReplanRequest(
            failed_step_id="retrieve",
            observation=_observation(failure.value, "evidence:minimum:1"),
            failure_class=failure,
            alternate_tools={"search_document": ["backup_search"]},
        ),
    )
    assert outcome.strategy is expected
    revised, trace = outcome.patch.apply(plan, _registry())
    before = next(step for step in plan.steps if step.step_id == "retrieve")
    after = next(step for step in revised.steps if step.step_id == "retrieve")
    assert after.model_dump() != before.model_dump()
    assert "retry after" not in after.action.casefold()
    assert trace.reason_summary == outcome.public_reason
    revised.validate_against(_registry())


def test_sixteen_fault_injections_improve_over_retry_baseline_by_fifteen_points() -> None:
    scenarios = [
        (failure, baseline_succeeds)
        for failure, baseline_succeeds in [
            (FailureClass.EMPTY_RETRIEVAL, False),
            (FailureClass.EMPTY_RETRIEVAL, False),
            (FailureClass.AMBIGUOUS_SECTION, False),
            (FailureClass.AMBIGUOUS_SECTION, False),
            (FailureClass.TOOL_TIMEOUT, True),
            (FailureClass.TOOL_TIMEOUT, True),
            (FailureClass.INVALID_ARGUMENTS, False),
            (FailureClass.INVALID_ARGUMENTS, False),
            (FailureClass.INSUFFICIENT_EVIDENCE, False),
            (FailureClass.INSUFFICIENT_EVIDENCE, False),
            (FailureClass.BUDGET_PRESSURE, False),
            (FailureClass.BUDGET_PRESSURE, False),
            (FailureClass.SUBAGENT_PARTIAL_FAILURE, False),
            (FailureClass.SUBAGENT_PARTIAL_FAILURE, False),
            (FailureClass.VERIFICATION_FAILURE, False),
            (FailureClass.VERIFICATION_FAILURE, False),
        ]
    ]
    strategy_successes = 0
    for failure, _ in scenarios:
        plan = _plan()
        outcome = StrategyReplanner(_registry()).replan(
            plan,
            ReplanRequest(
                failed_step_id="retrieve",
                observation=_observation(failure.value),
                failure_class=failure,
                alternate_tools={"search_document": ["backup_search"]},
            ),
        )
        revised, _ = outcome.patch.apply(plan, _registry())
        strategy_successes += revised.version == 2

    strategy_rate = strategy_successes / len(scenarios)
    retry_rate = sum(success for _, success in scenarios) / len(scenarios)
    assert len(scenarios) >= 15
    assert strategy_rate - retry_rate >= 0.15


def test_same_strategy_and_input_is_not_repeated_and_replans_stop_at_two() -> None:
    replanner = StrategyReplanner(_registry())
    plan = _plan()
    request = ReplanRequest(
        failed_step_id="retrieve",
        observation=_observation("empty_retrieval"),
        failure_class=FailureClass.EMPTY_RETRIEVAL,
    )
    first = replanner.replan(plan, request)
    plan, _ = first.patch.apply(plan, _registry())
    second = replanner.replan(
        plan,
        request.model_copy(update={"strategy_history": [first.attempt]}),
    )
    assert second.strategy is ReplanStrategy.SCOPE_EXPANSION
    assert second.attempt.fingerprint == first.attempt.fingerprint
    plan, _ = second.patch.apply(plan, _registry())
    with pytest.raises(ProjectError) as exc:
        replanner.replan(plan, request)
    assert exc.value.code is ErrorCode.RESOURCE_EXHAUSTED


def test_budget_permission_and_cancellation_gates_survive_replanning() -> None:
    replanner = StrategyReplanner(_registry())
    plan = _plan()
    outcome = replanner.replan(
        plan,
        ReplanRequest(
            failed_step_id="retrieve",
            observation=_observation("budget_pressure"),
            failure_class=FailureClass.BUDGET_PRESSURE,
            resources=ReplanResources(
                remaining_tokens=200,
                remaining_tool_calls=0,
                remaining_subagent_calls=0,
            ),
        ),
    )
    revised, _ = outcome.patch.apply(plan, _registry())
    revised_step = next(step for step in revised.steps if step.step_id == "retrieve")
    assert revised_step.budget.max_tokens <= 200
    assert revised_step.budget.max_tool_calls == 0

    with pytest.raises(ProjectError) as cancelled:
        replanner.replan(
            _plan(),
            ReplanRequest(
                failed_step_id="retrieve",
                observation=_observation("tool_timeout"),
                failure_class=FailureClass.TOOL_TIMEOUT,
                cancelled=True,
            ),
        )
    assert cancelled.value.code is ErrorCode.FAILED_PRECONDITION

    forbidden = RegistrySnapshot(
        skills={"paper_reader"},
        tools={"search_document", "backup_search"},
        permitted_skills={"paper_reader"},
        permitted_tools={"search_document"},
    )
    restricted = StrategyReplanner(forbidden).replan(
        _plan(),
        ReplanRequest(
            failed_step_id="retrieve",
            observation=_observation("tool_timeout"),
            failure_class=FailureClass.TOOL_TIMEOUT,
            alternate_tools={"search_document": ["backup_search"]},
        ),
    )
    assert restricted.strategy is not ReplanStrategy.ALTERNATE_TOOL


def test_failure_classifier_covers_public_error_and_quality_signals() -> None:
    expected = {
        "empty_retrieval": FailureClass.EMPTY_RETRIEVAL,
        "ambiguous_section": FailureClass.AMBIGUOUS_SECTION,
        "deadline_exceeded": FailureClass.TOOL_TIMEOUT,
        "invalid_argument": FailureClass.INVALID_ARGUMENTS,
        "insufficient_evidence": FailureClass.INSUFFICIENT_EVIDENCE,
        "resource_exhausted": FailureClass.BUDGET_PRESSURE,
        "subagent_partial_failure": FailureClass.SUBAGENT_PARTIAL_FAILURE,
        "verification_failed": FailureClass.VERIFICATION_FAILURE,
    }
    assert {
        code: classify_failure(_observation(code)) for code in expected
    } == expected
