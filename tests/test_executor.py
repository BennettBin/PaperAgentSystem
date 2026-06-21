import asyncio

import pytest

from agent_runtime.executor import (
    ExecutionBudget,
    ExecutionStatus,
    InMemoryExecutionStore,
    PlanExecutor,
)
from agent_runtime.planner import ExecutionPlan, PlanStep
from core.errors import ErrorCode, ProjectError
from core.ports.tools import Tool, ToolRegistry


def plan(tool_name: str = "echo") -> ExecutionPlan:
    return ExecutionPlan(
        goal="run",
        steps=[
            PlanStep(
                step_id="step-1",
                action="run tool",
                tool_name=tool_name,
                completion_condition="tool returns",
            )
        ],
    )


@pytest.mark.asyncio
async def test_executor_persists_each_step_and_is_idempotent() -> None:
    calls = 0

    async def echo(value: str) -> dict:
        nonlocal calls
        calls += 1
        return {"value": value}

    registry = ToolRegistry()
    registry.register(Tool("echo", "echo", [], echo))
    store = InMemoryExecutionStore()
    executor = PlanExecutor(registry, store)

    first = await executor.execute(
        "task-1",
        plan(),
        {"step-1": {"value": "ok"}},
        ExecutionBudget(max_steps=2),
    )
    second = await executor.execute(
        "task-1",
        plan(),
        {"step-1": {"value": "ok"}},
        ExecutionBudget(max_steps=2),
    )

    assert first.status is ExecutionStatus.COMPLETED
    assert second.status is ExecutionStatus.COMPLETED
    assert calls == 1
    assert store.events[-1]["step_id"] == "step-1"


@pytest.mark.asyncio
async def test_executor_checks_cancellation_before_action() -> None:
    registry = ToolRegistry()
    registry.register(Tool("echo", "echo", [], lambda: None))
    executor = PlanExecutor(registry, InMemoryExecutionStore())

    result = await executor.execute(
        "task-2",
        plan(),
        {},
        ExecutionBudget(max_steps=2),
        is_cancelled=lambda: True,
    )

    assert result.status is ExecutionStatus.CANCELLED
    assert result.completed_steps == []


@pytest.mark.asyncio
async def test_executor_times_out_and_points_to_failed_step() -> None:
    async def slow() -> None:
        await asyncio.sleep(0.1)

    registry = ToolRegistry()
    registry.register(Tool("slow", "slow", [], slow))
    executor = PlanExecutor(registry, InMemoryExecutionStore())

    result = await executor.execute(
        "task-3",
        plan("slow"),
        {},
        ExecutionBudget(max_steps=2, step_timeout_seconds=0.01),
    )

    assert result.status is ExecutionStatus.FAILED
    assert result.failed_step_id == "step-1"
    assert "timed out" in result.error


@pytest.mark.asyncio
async def test_executor_enforces_step_budget_and_registry() -> None:
    executor = PlanExecutor(ToolRegistry(), InMemoryExecutionStore())
    with pytest.raises(ProjectError) as missing:
        await executor.execute("task-4", plan("missing"), {}, ExecutionBudget(max_steps=2))
    assert missing.value.code is ErrorCode.TOOL_NOT_FOUND

    registry = ToolRegistry()

    async def echo() -> str:
        return "ok"

    registry.register(Tool("echo", "echo", [], echo))
    with pytest.raises(ProjectError) as budget:
        await PlanExecutor(registry, InMemoryExecutionStore()).execute(
            "task-5", plan(), {}, ExecutionBudget(max_steps=0)
        )
    assert budget.value.code is ErrorCode.RESOURCE_EXHAUSTED


@pytest.mark.asyncio
async def test_executor_enforces_token_and_subagent_budgets() -> None:
    class Invoker:
        def __init__(self) -> None:
            self.calls = 0

        async def invoke(self, name: str, arguments: dict) -> dict:
            self.calls += 1
            return {"name": name, **arguments}

    subagent = Invoker()
    subagent_plan = ExecutionPlan(
        goal="read",
        steps=[
            PlanStep(
                step_id="agent-1",
                action="delegate",
                subagent_name="paper_reader_agent",
                completion_condition="paper card returned",
            )
        ],
    )
    executor = PlanExecutor(
        ToolRegistry(),
        InMemoryExecutionStore(),
        subagent_invoker=subagent,
    )
    completed = await executor.execute(
        "task-6",
        subagent_plan,
        {"agent-1": {"file_id": "f1"}},
        ExecutionBudget(max_subagent_calls=1),
    )
    assert completed.status is ExecutionStatus.COMPLETED
    assert subagent.calls == 1

    with pytest.raises(ProjectError) as tokens:
        await executor.execute(
            "task-7",
            subagent_plan,
            {"agent-1": {"content": "x" * 100}},
            ExecutionBudget(max_tokens=1),
        )
    assert tokens.value.code is ErrorCode.RESOURCE_EXHAUSTED
