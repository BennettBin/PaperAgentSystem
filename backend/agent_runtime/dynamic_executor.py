"""Version-aware dynamic Plan execution with atomic resumable checkpoints."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Sequence
from enum import StrEnum
from time import monotonic
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from backend.agent_runtime.completion_evaluator import (
    ClaimEvidence,
    CompletionEvaluationInput,
    CompletionEvaluator,
    EvidenceRecord,
    NumericCheck,
)
from backend.agent_runtime.planner import (
    ExecutionPlan,
    Observation,
    ObservationStatus,
    PlanStep,
    RegistrySnapshot,
    UsageRecord,
)
from backend.agent_runtime.strategy_replanner import (
    ReplanRequest,
    ReplanResources,
    StrategyAttempt,
    StrategyReplanner,
)
from backend.core.errors import ErrorCode, ProjectError


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RuntimeStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ASK_USER = "ask_user"


class RuntimeBudgetBalance(_StrictModel):
    remaining_tokens: int = Field(ge=0)
    remaining_tool_calls: int = Field(ge=0)
    remaining_subagent_calls: int = Field(ge=0)


class StepRunResult(_StrictModel):
    output: Any
    usage: UsageRecord = Field(default_factory=UsageRecord)


class RuntimeTrace(_StrictModel):
    sequence: int = Field(ge=1)
    event: str = Field(min_length=1)
    plan_version: int = Field(ge=0)
    step_id: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class DynamicExecutionCheckpoint(_StrictModel):
    task_id: str = Field(min_length=1)
    status: RuntimeStatus
    plan: ExecutionPlan
    completed_step_ids: list[str] = Field(default_factory=list)
    outputs: dict[str, Any] = Field(default_factory=dict)
    observations: list[Observation] = Field(default_factory=list)
    traces: list[RuntimeTrace] = Field(default_factory=list)
    strategy_history: list[StrategyAttempt] = Field(default_factory=list)
    inflight: dict[str, str] = Field(default_factory=dict)
    budget: RuntimeBudgetBalance
    revision: int = Field(default=0, ge=0)


class DynamicActionRunner(Protocol):
    async def invoke(
        self,
        step: PlanStep,
        arguments: dict[str, Any],
        *,
        idempotency_key: str,
    ) -> StepRunResult: ...


class DynamicExecutionStore(Protocol):
    async def load(self, task_id: str) -> DynamicExecutionCheckpoint | None: ...

    async def persist(
        self,
        checkpoint: DynamicExecutionCheckpoint,
        *,
        expected_revision: int | None,
    ) -> DynamicExecutionCheckpoint: ...


class InMemoryDynamicExecutionStore:
    """CAS store used by tests and local adapters; durable adapters keep the same Port."""

    def __init__(self) -> None:
        self._items: dict[str, DynamicExecutionCheckpoint] = {}
        self._lock = asyncio.Lock()
        self.events: list[DynamicExecutionCheckpoint] = []

    async def load(self, task_id: str) -> DynamicExecutionCheckpoint | None:
        async with self._lock:
            item = self._items.get(task_id)
            return item.model_copy(deep=True) if item else None

    async def persist(
        self,
        checkpoint: DynamicExecutionCheckpoint,
        *,
        expected_revision: int | None,
    ) -> DynamicExecutionCheckpoint:
        async with self._lock:
            current = self._items.get(checkpoint.task_id)
            actual = current.revision if current else None
            if actual != expected_revision:
                raise ProjectError(
                    ErrorCode.FAILED_PRECONDITION,
                    "Dynamic execution checkpoint revision conflict",
                    {
                        "task_id": checkpoint.task_id,
                        "expected_revision": expected_revision,
                        "actual_revision": actual,
                    },
                )
            saved = checkpoint.model_copy(
                deep=True,
                update={"revision": (actual or 0) + 1},
            )
            self._items[checkpoint.task_id] = saved
            self.events.append(saved.model_copy(deep=True))
            return saved.model_copy(deep=True)


class _CancellationRequested(Exception):
    pass


class DynamicPlanExecutor:
    """Execute ready steps, persist atomic observations and apply bounded replans."""

    TERMINAL = {
        RuntimeStatus.COMPLETED,
        RuntimeStatus.FAILED,
        RuntimeStatus.CANCELLED,
        RuntimeStatus.ASK_USER,
    }

    def __init__(
        self,
        *,
        runner: DynamicActionRunner,
        store: DynamicExecutionStore,
        completion_evaluator: CompletionEvaluator,
        replanner: StrategyReplanner,
        registry: RegistrySnapshot,
        alternate_tools: dict[str, list[str]] | None = None,
    ) -> None:
        self._runner = runner
        self._store = store
        self._completion = completion_evaluator
        self._replanner = replanner
        self._registry = registry
        self._alternate_tools = alternate_tools or {}

    async def execute(
        self,
        task_id: str,
        plan: ExecutionPlan,
        step_arguments: dict[str, dict[str, Any]] | None = None,
        *,
        cancel_event: asyncio.Event | None = None,
    ) -> DynamicExecutionCheckpoint:
        plan.validate_against(self._registry)
        checkpoint = await self._store.load(task_id)
        if checkpoint is None:
            checkpoint = DynamicExecutionCheckpoint(
                task_id=task_id,
                status=RuntimeStatus.RUNNING,
                plan=plan,
                budget=RuntimeBudgetBalance(
                    remaining_tokens=plan.global_budget.max_tokens,
                    remaining_tool_calls=plan.global_budget.max_tool_calls,
                    remaining_subagent_calls=plan.global_budget.max_subagent_calls,
                ),
            )
            checkpoint = await self._store.persist(
                checkpoint, expected_revision=None
            )
        elif checkpoint.plan.plan_id != plan.plan_id:
            raise ProjectError(
                ErrorCode.FAILED_PRECONDITION,
                "Cannot resume a task with a different Plan identity",
                {"task_id": task_id},
            )
        if checkpoint.status in self.TERMINAL:
            return checkpoint

        arguments = step_arguments or {}
        started = monotonic()
        while checkpoint.status is RuntimeStatus.RUNNING:
            if cancel_event and cancel_event.is_set():
                return await self._terminal(checkpoint, RuntimeStatus.CANCELLED)
            if monotonic() - started >= checkpoint.plan.global_budget.max_duration_ms / 1000:
                return await self._terminal(
                    checkpoint,
                    RuntimeStatus.FAILED,
                    error="execution_duration_exceeded",
                )
            if len(checkpoint.completed_step_ids) == len(checkpoint.plan.steps):
                return await self._terminal(checkpoint, RuntimeStatus.COMPLETED)

            ready = _ready_steps(checkpoint)
            if not ready:
                return await self._terminal(
                    checkpoint,
                    RuntimeStatus.FAILED,
                    error="no_ready_steps",
                )
            batch = _compatible_batch(
                ready, checkpoint.plan.global_budget.max_parallel_steps
            )
            inadmissible = next(
                (step for step in batch if not _budget_allows(checkpoint.budget, step)),
                None,
            )
            if inadmissible is not None:
                observation = Observation(
                    step_id=inadmissible.step_id,
                    status=ObservationStatus.REPLAN,
                    error_code="budget_pressure",
                    missing_items=["budget:remaining"],
                    quality_signal={"budget_admitted": False},
                )
                checkpoint = await self._record_observation(checkpoint, observation)
                checkpoint = await self._apply_replan(checkpoint, observation)
                continue

            checkpoint = await self._claim_batch(checkpoint, batch)
            tasks = [
                asyncio.create_task(
                    self._run_step(
                        step,
                        _arguments_for(step, arguments, checkpoint.outputs),
                        checkpoint.inflight[step.step_id],
                        cancel_event,
                    )
                )
                for step in batch
            ]
            try:
                results = await asyncio.gather(*tasks)
            except _CancellationRequested:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                return await self._terminal(checkpoint, RuntimeStatus.CANCELLED)
            except BaseException:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                raise

            for step, result in zip(batch, results, strict=True):
                if isinstance(result, Exception):
                    observation = _failure_observation(step, result)
                    checkpoint.inflight.pop(step.step_id, None)
                    checkpoint = await self._record_observation(
                        checkpoint, observation
                    )
                    checkpoint = await self._apply_replan(checkpoint, observation)
                    continue

                quality_input = _quality_input(result.output)
                evaluation = self._completion.evaluate(step, quality_input)
                checkpoint = _deduct_usage(checkpoint, result.usage)
                checkpoint.inflight.pop(step.step_id, None)
                checkpoint.observations.append(evaluation.observation)
                checkpoint.traces.append(
                    _trace(
                        checkpoint,
                        "step_observed",
                        step.step_id,
                        {
                            "status": evaluation.decision.value,
                            "usage": result.usage.model_dump(mode="json"),
                            "missing_items": evaluation.missing_items,
                        },
                    )
                )
                if evaluation.decision is ObservationStatus.COMPLETE:
                    checkpoint.completed_step_ids.append(step.step_id)
                    checkpoint.outputs[step.step_id] = result.output
                    checkpoint.traces.append(
                        _trace(checkpoint, "step_committed", step.step_id)
                    )
                    checkpoint = await self._persist(checkpoint)
                elif evaluation.decision in {
                    ObservationStatus.REPAIR,
                    ObservationStatus.REPLAN,
                }:
                    checkpoint = await self._persist(checkpoint)
                    checkpoint = await self._apply_replan(
                        checkpoint, evaluation.observation
                    )
                elif evaluation.decision is ObservationStatus.ASK_USER:
                    checkpoint = await self._persist(checkpoint)
                    return await self._terminal(checkpoint, RuntimeStatus.ASK_USER)
                else:
                    checkpoint = await self._persist(checkpoint)
                    return await self._terminal(checkpoint, RuntimeStatus.FAILED)
        return checkpoint

    async def _run_step(
        self,
        step: PlanStep,
        arguments: dict[str, Any],
        idempotency_key: str,
        cancel_event: asyncio.Event | None,
    ) -> StepRunResult | Exception:
        try:
            action = asyncio.create_task(
                asyncio.wait_for(
                    self._runner.invoke(
                        step, arguments, idempotency_key=idempotency_key
                    ),
                    timeout=step.budget.timeout_ms / 1000,
                )
            )
            if cancel_event is None:
                return await action
            cancelled = asyncio.create_task(cancel_event.wait())
            done, _ = await asyncio.wait(
                {action, cancelled}, return_when=asyncio.FIRST_COMPLETED
            )
            if cancelled in done and cancel_event.is_set():
                action.cancel()
                await asyncio.gather(action, return_exceptions=True)
                raise _CancellationRequested()
            cancelled.cancel()
            await asyncio.gather(cancelled, return_exceptions=True)
            return await action
        except _CancellationRequested:
            raise
        except Exception as exc:
            return exc

    async def _claim_batch(
        self,
        checkpoint: DynamicExecutionCheckpoint,
        batch: Sequence[PlanStep],
    ) -> DynamicExecutionCheckpoint:
        changed = False
        for step in batch:
            if step.step_id in checkpoint.inflight:
                continue
            checkpoint.inflight[step.step_id] = _idempotency_key(
                checkpoint.task_id,
                checkpoint.plan.plan_id,
                checkpoint.plan.version,
                step.step_id,
            )
            checkpoint.traces.append(
                _trace(
                    checkpoint,
                    "step_claimed",
                    step.step_id,
                    {"idempotency_key": checkpoint.inflight[step.step_id]},
                )
            )
            changed = True
        return await self._persist(checkpoint) if changed else checkpoint

    async def _record_observation(
        self,
        checkpoint: DynamicExecutionCheckpoint,
        observation: Observation,
    ) -> DynamicExecutionCheckpoint:
        checkpoint.observations.append(observation)
        checkpoint.traces.append(
            _trace(
                checkpoint,
                "step_observed",
                observation.step_id,
                {
                    "status": observation.status.value,
                    "error_code": observation.error_code,
                    "missing_items": observation.missing_items,
                },
            )
        )
        return await self._persist(checkpoint)

    async def _apply_replan(
        self,
        checkpoint: DynamicExecutionCheckpoint,
        observation: Observation,
    ) -> DynamicExecutionCheckpoint:
        try:
            outcome = self._replanner.replan(
                checkpoint.plan,
                ReplanRequest(
                    failed_step_id=observation.step_id,
                    observation=observation,
                    alternate_tools=self._alternate_tools,
                    resources=ReplanResources(
                        remaining_tokens=checkpoint.budget.remaining_tokens,
                        remaining_tool_calls=checkpoint.budget.remaining_tool_calls,
                        remaining_subagent_calls=checkpoint.budget.remaining_subagent_calls,
                    ),
                    strategy_history=checkpoint.strategy_history,
                ),
            )
            revised, _ = outcome.patch.apply(checkpoint.plan, self._registry)
        except ProjectError as exc:
            return await self._terminal(
                checkpoint,
                RuntimeStatus.FAILED,
                error=exc.code.value,
            )
        checkpoint.plan = revised
        checkpoint.strategy_history.append(outcome.attempt)
        checkpoint.traces.append(
            _trace(
                checkpoint,
                "plan_revised",
                observation.step_id,
                {
                    "strategy": outcome.strategy.value,
                    "reason": outcome.public_reason,
                },
            )
        )
        return await self._persist(checkpoint)

    async def _terminal(
        self,
        checkpoint: DynamicExecutionCheckpoint,
        status: RuntimeStatus,
        *,
        error: str | None = None,
    ) -> DynamicExecutionCheckpoint:
        checkpoint.status = status
        checkpoint.traces.append(
            _trace(
                checkpoint,
                "terminal",
                data={"status": status.value, "error": error},
            )
        )
        return await self._persist(checkpoint)

    async def _persist(
        self, checkpoint: DynamicExecutionCheckpoint
    ) -> DynamicExecutionCheckpoint:
        return await self._store.persist(
            checkpoint,
            expected_revision=checkpoint.revision,
        )


def _ready_steps(checkpoint: DynamicExecutionCheckpoint) -> list[PlanStep]:
    completed = set(checkpoint.completed_step_ids)
    return [
        step
        for step in checkpoint.plan.steps
        if step.step_id not in completed and set(step.depends_on) <= completed
    ]


def _compatible_batch(ready: list[PlanStep], limit: int) -> list[PlanStep]:
    selected: list[PlanStep] = []
    side_effect_groups: set[str] = set()
    for step in ready:
        if len(selected) >= limit:
            break
        if step.side_effect_group and step.side_effect_group in side_effect_groups:
            continue
        selected.append(step)
        if step.side_effect_group:
            side_effect_groups.add(step.side_effect_group)
    return selected


def _budget_allows(balance: RuntimeBudgetBalance, step: PlanStep) -> bool:
    if step.budget.max_tokens and step.budget.max_tokens > balance.remaining_tokens:
        return False
    if step.tool_name and balance.remaining_tool_calls < 1:
        return False
    if step.subagent_name and balance.remaining_subagent_calls < 1:
        return False
    return True


def _deduct_usage(
    checkpoint: DynamicExecutionCheckpoint,
    usage: UsageRecord,
) -> DynamicExecutionCheckpoint:
    tokens = usage.input_tokens + usage.output_tokens
    if (
        tokens > checkpoint.budget.remaining_tokens
        or usage.tool_calls > checkpoint.budget.remaining_tool_calls
        or usage.subagent_calls > checkpoint.budget.remaining_subagent_calls
    ):
        raise ProjectError(
            ErrorCode.RESOURCE_EXHAUSTED,
            "Step usage exceeds reserved runtime budget",
        )
    checkpoint.budget = RuntimeBudgetBalance(
        remaining_tokens=checkpoint.budget.remaining_tokens - tokens,
        remaining_tool_calls=(
            checkpoint.budget.remaining_tool_calls - usage.tool_calls
        ),
        remaining_subagent_calls=(
            checkpoint.budget.remaining_subagent_calls - usage.subagent_calls
        ),
    )
    return checkpoint


def _arguments_for(
    step: PlanStep,
    arguments: dict[str, dict[str, Any]],
    outputs: dict[str, Any],
) -> dict[str, Any]:
    result = dict(arguments.get(step.step_id, {}))
    result["dependency_outputs"] = {
        dependency: outputs[dependency]
        for dependency in step.depends_on
        if dependency in outputs
    }
    return result


def _quality_input(output: Any) -> CompletionEvaluationInput:
    payload = dict(output) if isinstance(output, dict) else {"result": output}
    claims = [
        ClaimEvidence.model_validate(item)
        for item in payload.get("claims", [])
        if isinstance(item, dict)
    ]
    evidence = [
        EvidenceRecord.model_validate(item)
        for item in payload.get("evidence", [])
        if isinstance(item, dict)
    ]
    numeric_checks = [
        NumericCheck.model_validate(item)
        for item in payload.get("numeric_checks", [])
        if isinstance(item, dict)
    ]
    return CompletionEvaluationInput(
        output=payload,
        claims=claims,
        evidence=evidence,
        numeric_checks=numeric_checks,
        target_paper_ids=[str(item) for item in payload.get("target_paper_ids", [])],
        immutable_terms=[str(item) for item in payload.get("immutable_terms", [])],
        review_required=bool(payload.get("review_required", False)),
        artifact_ref=(
            str(payload["artifact_ref"]) if payload.get("artifact_ref") else None
        ),
    )


def _failure_observation(step: PlanStep, exc: Exception) -> Observation:
    if isinstance(exc, TimeoutError):
        code = "tool_timeout"
    elif isinstance(exc, ProjectError):
        code = exc.code.value
    elif step.subagent_name:
        code = "subagent_partial_failure"
    else:
        code = "invalid_argument"
    return Observation(
        step_id=step.step_id,
        status=ObservationStatus.REPLAN,
        error_code=code,
        retryable=True,
        missing_items=[f"execution:{code}"],
    )


def _idempotency_key(
    task_id: str,
    plan_id: str,
    plan_version: int,
    step_id: str,
) -> str:
    raw = f"{task_id}:{plan_id}:{plan_version}:{step_id}".encode()
    return hashlib.sha256(raw).hexdigest()


def _trace(
    checkpoint: DynamicExecutionCheckpoint,
    event: str,
    step_id: str | None = None,
    data: dict[str, Any] | None = None,
) -> RuntimeTrace:
    return RuntimeTrace(
        sequence=len(checkpoint.traces) + 1,
        event=event,
        plan_version=checkpoint.plan.version,
        step_id=step_id,
        data=data or {},
    )
