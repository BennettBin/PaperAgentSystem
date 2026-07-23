from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

import pytest

from backend.agent_runtime.completion_evaluator import CompletionEvaluator
from backend.agent_runtime.dynamic_executor import (
    DynamicPlanExecutor,
    InMemoryDynamicExecutionStore,
    RuntimeStatus,
    StepRunResult,
)
from backend.agent_runtime.planner import (
    CompletionPredicate,
    ExecutionPlan,
    PlanBudget,
    PlanStep,
    RegistrySnapshot,
    StepBudget,
    StepType,
    UsageRecord,
)
from backend.agent_runtime.strategy_replanner import StrategyReplanner


class SimulatedProcessCrash(BaseException):
    pass


class IdempotentRunner:
    def __init__(self, *, crash_once: bool = False, delay: float = 0.0) -> None:
        self.crash_once = crash_once
        self.delay = delay
        self.cache: dict[str, StepRunResult] = {}
        self.calls: defaultdict[str, int] = defaultdict(int)
        self.artifact_writes = 0
        self.active = 0
        self.max_active = 0

    async def invoke(
        self,
        step: PlanStep,
        arguments: dict[str, Any],
        *,
        idempotency_key: str,
    ) -> StepRunResult:
        self.calls[step.step_id] += 1
        if idempotency_key in self.cache:
            return self.cache[idempotency_key]
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            dependencies = arguments.get("dependency_outputs", {})
            result = StepRunResult(
                output={"value": step.step_id, "dependencies": dependencies},
                usage=UsageRecord(
                    input_tokens=5,
                    output_tokens=5,
                    tool_calls=1 if step.step_type is StepType.TOOL_CALL else 0,
                ),
            )
            self.cache[idempotency_key] = result
            if step.side_effect_group:
                self.artifact_writes += 1
            if self.crash_once:
                self.crash_once = False
                raise SimulatedProcessCrash()
            return result
        finally:
            self.active -= 1


class RepairThenSucceedRunner(IdempotentRunner):
    async def invoke(
        self,
        step: PlanStep,
        arguments: dict[str, Any],
        *,
        idempotency_key: str,
    ) -> StepRunResult:
        call = sum(self.calls.values())
        self.calls[step.step_id] += 1
        if call == 0:
            return StepRunResult(
                output={"answer": "unsupported", "claims": [{"claim_id": "C1", "text": "fact"}]},
                usage=UsageRecord(input_tokens=5, output_tokens=5),
            )
        return StepRunResult(
            output={
                "answer": "supported [E1]",
                "claims": [{"claim_id": "C1", "text": "fact", "evidence_ids": ["E1"]}],
                "evidence": [
                    {
                        "evidence_id": "E1",
                        "source_id": "paper-a",
                        "page_number": 1,
                        "claim_ids": ["C1"],
                    }
                ],
            },
            usage=UsageRecord(input_tokens=5, output_tokens=5),
        )


def _registry() -> RegistrySnapshot:
    return RegistrySnapshot(
        skills=set(),
        tools={"search_document", "save_artifact"},
        permitted_tools={"search_document", "save_artifact"},
    )


def _executor(store: InMemoryDynamicExecutionStore, runner: IdempotentRunner) -> DynamicPlanExecutor:
    return DynamicPlanExecutor(
        runner=runner,
        store=store,
        completion_evaluator=CompletionEvaluator(),
        replanner=StrategyReplanner(_registry()),
        registry=_registry(),
    )


def _step(
    step_id: str,
    *,
    depends_on: list[str] | None = None,
    side_effect_group: str | None = None,
    evidence: bool = False,
) -> PlanStep:
    return PlanStep(
        step_id=step_id,
        action=f"run {step_id}",
        step_type=StepType.TOOL_CALL,
        tool_name="save_artifact" if side_effect_group else "search_document",
        depends_on=depends_on or [],
        side_effect_group=side_effect_group,
        budget=StepBudget(max_tokens=50, max_tool_calls=1, timeout_ms=1000),
        completion_predicate=CompletionPredicate(
            kind="answer_with_evidence" if evidence else "schema_complete",
            required_fields=["answer"] if evidence else ["value"],
            minimum_evidence=1 if evidence else 0,
        ),
    )


def _plan(*steps: PlanStep, max_parallel_steps: int = 2) -> ExecutionPlan:
    return ExecutionPlan(
        goal="dynamic execution",
        global_budget=PlanBudget(
            max_tokens=1000,
            max_tool_calls=10,
            max_subagent_calls=0,
            max_duration_ms=30_000,
            max_parallel_steps=max_parallel_steps,
        ),
        steps=list(steps),
    )


@pytest.mark.asyncio
async def test_crash_resume_reuses_idempotency_key_without_duplicate_artifact_or_budget() -> None:
    store = InMemoryDynamicExecutionStore()
    runner = IdempotentRunner(crash_once=True)
    plan = _plan(_step("write", side_effect_group="artifact:report"))
    with pytest.raises(SimulatedProcessCrash):
        await _executor(store, runner).execute("task-crash", plan)

    claimed = await store.load("task-crash")
    assert claimed is not None
    assert claimed.inflight["write"]
    assert claimed.budget.remaining_tokens == 1000

    result = await _executor(store, runner).execute("task-crash", plan)
    assert result.status is RuntimeStatus.COMPLETED
    assert runner.artifact_writes == 1
    assert runner.calls["write"] == 2
    assert result.budget.remaining_tokens == 990
    assert len([trace for trace in result.traces if trace.event == "step_committed"]) == 1


@pytest.mark.asyncio
async def test_parallel_and_serial_execution_have_same_dependency_semantics() -> None:
    plan = _plan(
        _step("a"),
        _step("b"),
        _step("merge", depends_on=["a", "b"]),
    )
    parallel_runner = IdempotentRunner(delay=0.02)
    parallel = await _executor(
        InMemoryDynamicExecutionStore(), parallel_runner
    ).execute("parallel", plan)
    serial_runner = IdempotentRunner(delay=0.01)
    serial = await _executor(InMemoryDynamicExecutionStore(), serial_runner).execute(
        "serial", plan.model_copy(update={"global_budget": plan.global_budget.model_copy(update={"max_parallel_steps": 1})})
    )
    assert parallel.outputs["merge"] == serial.outputs["merge"]
    assert parallel_runner.max_active == 2
    assert serial_runner.max_active == 1


@pytest.mark.asyncio
async def test_conflicting_side_effect_groups_are_serialized() -> None:
    runner = IdempotentRunner(delay=0.02)
    plan = _plan(
        _step("write-a", side_effect_group="artifact:report"),
        _step("write-b", side_effect_group="artifact:report"),
    )
    result = await _executor(InMemoryDynamicExecutionStore(), runner).execute(
        "side-effects", plan
    )
    assert result.status is RuntimeStatus.COMPLETED
    assert runner.max_active == 1


@pytest.mark.asyncio
async def test_cancellation_propagates_to_running_action_under_two_seconds() -> None:
    loop = asyncio.get_running_loop()
    latencies: list[float] = []
    for index in range(20):
        runner = IdempotentRunner(delay=10.0)
        cancel = asyncio.Event()
        task = asyncio.create_task(
            _executor(InMemoryDynamicExecutionStore(), runner).execute(
                f"cancel-{index}", _plan(_step("slow")), cancel_event=cancel
            )
        )
        await asyncio.sleep(0.01)
        started = loop.time()
        cancel.set()
        result = await asyncio.wait_for(task, timeout=2.0)
        latencies.append(loop.time() - started)
        assert result.status is RuntimeStatus.CANCELLED
        assert runner.active == 0
        assert result.completed_step_ids == []
    p95 = sorted(latencies)[18]
    assert p95 < 2.0


@pytest.mark.asyncio
async def test_quality_failure_replans_and_trace_plan_state_remain_consistent() -> None:
    store = InMemoryDynamicExecutionStore()
    runner = RepairThenSucceedRunner()
    result = await _executor(store, runner).execute(
        "repair", _plan(_step("answer", evidence=True))
    )
    assert result.status is RuntimeStatus.COMPLETED
    assert result.plan.version == 2
    assert result.plan.replan_count == 1
    assert [item.status.value for item in result.observations] == ["repair", "complete"]
    assert [trace.event for trace in result.traces].count("plan_revised") == 1
    assert all(trace.plan_version <= result.plan.version for trace in result.traces)
    assert result.budget.remaining_tokens == 980
