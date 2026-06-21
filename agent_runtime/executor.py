"""Budgeted, cancellable and idempotent plan execution."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from time import monotonic
from typing import Any, Protocol

from agent_runtime.planner import ExecutionPlan
from core.errors import ErrorCode, ProjectError
from core.ports.tools import ToolRegistry


class ExecutionStatus(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class ExecutionBudget:
    max_steps: int = 8
    max_tokens: int = 16_000
    max_tool_calls: int = 8
    max_subagent_calls: int = 2
    max_concurrency: int = 1
    step_timeout_seconds: float = 60.0
    max_duration_seconds: float = 600.0


@dataclass(slots=True)
class ExecutionResult:
    task_id: str
    status: ExecutionStatus
    completed_steps: list[str] = field(default_factory=list)
    outputs: dict[str, Any] = field(default_factory=dict)
    failed_step_id: str | None = None
    error: str = ""


class ExecutionStore(Protocol):
    async def get_step_result(self, task_id: str, step_id: str) -> Any | None: ...
    async def save_step_result(self, task_id: str, step_id: str, result: Any) -> None: ...


class ActionInvoker(Protocol):
    async def invoke(self, name: str, arguments: dict[str, Any]) -> Any: ...


class InMemoryExecutionStore:
    def __init__(self) -> None:
        self.results: dict[tuple[str, str], Any] = {}
        self.events: list[dict[str, Any]] = []

    async def get_step_result(self, task_id: str, step_id: str) -> Any | None:
        return self.results.get((task_id, step_id))

    async def save_step_result(self, task_id: str, step_id: str, result: Any) -> None:
        self.results[(task_id, step_id)] = result
        self.events.append({"task_id": task_id, "step_id": step_id, "result": result})


class PlanExecutor:
    def __init__(
        self,
        tools: ToolRegistry,
        store: ExecutionStore,
        *,
        skill_invoker: ActionInvoker | None = None,
        subagent_invoker: ActionInvoker | None = None,
    ) -> None:
        self._tools = tools
        self._store = store
        self._skill_invoker = skill_invoker
        self._subagent_invoker = subagent_invoker

    async def execute(
        self,
        task_id: str,
        plan: ExecutionPlan,
        step_arguments: dict[str, dict[str, Any]],
        budget: ExecutionBudget,
        *,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> ExecutionResult:
        if len(plan.steps) > budget.max_steps:
            raise ProjectError(ErrorCode.RESOURCE_EXHAUSTED, "Execution step budget exceeded")
        if budget.max_concurrency < 1:
            raise ProjectError(ErrorCode.INVALID_ARGUMENT, "Concurrency budget must be positive")
        result = ExecutionResult(task_id=task_id, status=ExecutionStatus.COMPLETED)
        tool_calls = 0
        subagent_calls = 0
        tokens_used = 0
        started = monotonic()
        by_id = {step.step_id: step for step in plan.steps}
        for step_id in plan.topological_order():
            if is_cancelled and is_cancelled():
                result.status = ExecutionStatus.CANCELLED
                return result
            if monotonic() - started >= budget.max_duration_seconds:
                result.status = ExecutionStatus.FAILED
                result.failed_step_id = step_id
                result.error = f"Step {step_id} exceeded total time budget"
                return result
            step = by_id[step_id]
            arguments = step_arguments.get(step_id, {})
            tokens_used += self._estimate_tokens(arguments)
            if tokens_used > budget.max_tokens:
                raise ProjectError(
                    ErrorCode.RESOURCE_EXHAUSTED,
                    "Token budget exceeded",
                    {"step_id": step_id},
                )
            cached = await self._store.get_step_result(task_id, step_id)
            if cached is not None:
                result.completed_steps.append(step_id)
                result.outputs[step_id] = cached
                continue
            if step.tool_name:
                tool = self._tools.get(step.tool_name)
                if tool is None:
                    raise ProjectError(
                        ErrorCode.TOOL_NOT_FOUND,
                        f"Unregistered Tool: {step.tool_name}",
                        {"step_id": step_id},
                    )
                tool_calls += 1
                if tool_calls > budget.max_tool_calls:
                    raise ProjectError(
                        ErrorCode.RESOURCE_EXHAUSTED,
                        "Tool-call budget exceeded",
                        {"step_id": step_id},
                    )
                try:
                    output = await asyncio.wait_for(
                        tool.execute(**arguments),
                        timeout=budget.step_timeout_seconds,
                    )
                except TimeoutError:
                    result.status = ExecutionStatus.FAILED
                    result.failed_step_id = step_id
                    result.error = f"Step {step_id} timed out"
                    return result
                except Exception as exc:
                    result.status = ExecutionStatus.FAILED
                    result.failed_step_id = step_id
                    result.error = f"Step {step_id} failed: {exc}"
                    return result
            elif step.subagent_name:
                subagent_calls += 1
                if subagent_calls > budget.max_subagent_calls:
                    raise ProjectError(
                        ErrorCode.RESOURCE_EXHAUSTED,
                        "Sub Agent budget exceeded",
                        {"step_id": step_id},
                    )
                if self._subagent_invoker is None:
                    raise ProjectError(
                        ErrorCode.UNAVAILABLE,
                        "Sub Agent invoker is unavailable",
                        {"step_id": step_id},
                    )
                output = await asyncio.wait_for(
                    self._subagent_invoker.invoke(step.subagent_name, arguments),
                    timeout=budget.step_timeout_seconds,
                )
            elif step.skill_name and self._skill_invoker:
                output = await asyncio.wait_for(
                    self._skill_invoker.invoke(step.skill_name, arguments),
                    timeout=budget.step_timeout_seconds,
                )
            else:
                output = {"skill": step.skill_name, "status": "prepared"}
            tokens_used += self._estimate_tokens(output)
            if tokens_used > budget.max_tokens:
                raise ProjectError(
                    ErrorCode.RESOURCE_EXHAUSTED,
                    "Token budget exceeded",
                    {"step_id": step_id},
                )
            await self._store.save_step_result(task_id, step_id, output)
            result.completed_steps.append(step_id)
            result.outputs[step_id] = output
        return result

    @staticmethod
    def _estimate_tokens(value: Any) -> int:
        return (len(str(value)) + 3) // 4
