"""Bounded failure-aware replanning that emits auditable Plan patches."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from backend.agent_runtime.planner import (
    ExecutionPlan,
    Observation,
    PlanPatch,
    PlanPatchOperation,
    PlanStep,
    RegistrySnapshot,
    StepBudget,
    StepType,
)
from backend.core.errors import ErrorCode, ProjectError


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FailureClass(StrEnum):
    EMPTY_RETRIEVAL = "empty_retrieval"
    AMBIGUOUS_SECTION = "ambiguous_section"
    TOOL_TIMEOUT = "tool_timeout"
    INVALID_ARGUMENTS = "invalid_arguments"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    BUDGET_PRESSURE = "budget_pressure"
    SUBAGENT_PARTIAL_FAILURE = "subagent_partial_failure"
    VERIFICATION_FAILURE = "verification_failure"


class ReplanStrategy(StrEnum):
    QUERY_REWRITE = "query_rewrite"
    SCOPE_EXPANSION = "scope_expansion"
    ALTERNATE_TOOL = "alternate_tool"
    MODEL_ESCALATION = "model_escalation"
    EVIDENCE_ACQUISITION = "evidence_acquisition"
    PARTIAL_AGGREGATION = "partial_aggregation"
    ASK_USER = "ask_user"
    ARGUMENT_REPAIR = "argument_repair"
    CONTEXT_COMPRESSION = "context_compression"
    REDUCE_CANDIDATES = "reduce_candidates"
    DEGRADED_OUTPUT = "degraded_output"


class ReplanResources(_StrictModel):
    remaining_tokens: int = Field(default=16_000, ge=0)
    remaining_tool_calls: int = Field(default=8, ge=0)
    remaining_subagent_calls: int = Field(default=2, ge=0)


class StrategyAttempt(_StrictModel):
    failure_class: FailureClass
    failed_step_id: str
    strategy: ReplanStrategy
    fingerprint: str


class ReplanRequest(_StrictModel):
    failed_step_id: str = Field(min_length=1)
    observation: Observation
    failure_class: FailureClass | None = None
    alternate_tools: dict[str, list[str]] = Field(default_factory=dict)
    resources: ReplanResources = Field(default_factory=ReplanResources)
    strategy_history: list[StrategyAttempt] = Field(default_factory=list)
    cancelled: bool = False


class StrategyReplanOutcome(_StrictModel):
    strategy: ReplanStrategy
    public_reason: str
    attempt: StrategyAttempt
    patch: PlanPatch


_ERROR_CLASS: dict[str, FailureClass] = {
    "empty_retrieval": FailureClass.EMPTY_RETRIEVAL,
    "ambiguous_section": FailureClass.AMBIGUOUS_SECTION,
    "deadline_exceeded": FailureClass.TOOL_TIMEOUT,
    "tool_timeout": FailureClass.TOOL_TIMEOUT,
    "invalid_argument": FailureClass.INVALID_ARGUMENTS,
    "invalid_arguments": FailureClass.INVALID_ARGUMENTS,
    "insufficient_evidence": FailureClass.INSUFFICIENT_EVIDENCE,
    "completion_predicate_failed": FailureClass.INSUFFICIENT_EVIDENCE,
    "resource_exhausted": FailureClass.BUDGET_PRESSURE,
    "budget_pressure": FailureClass.BUDGET_PRESSURE,
    "subagent_partial_failure": FailureClass.SUBAGENT_PARTIAL_FAILURE,
    "verification_failed": FailureClass.VERIFICATION_FAILURE,
    "verification_failure": FailureClass.VERIFICATION_FAILURE,
}

_CANDIDATES: dict[FailureClass, tuple[ReplanStrategy, ...]] = {
    FailureClass.EMPTY_RETRIEVAL: (
        ReplanStrategy.QUERY_REWRITE,
        ReplanStrategy.SCOPE_EXPANSION,
        ReplanStrategy.ASK_USER,
    ),
    FailureClass.AMBIGUOUS_SECTION: (
        ReplanStrategy.ASK_USER,
        ReplanStrategy.SCOPE_EXPANSION,
    ),
    FailureClass.TOOL_TIMEOUT: (
        ReplanStrategy.ALTERNATE_TOOL,
        ReplanStrategy.MODEL_ESCALATION,
        ReplanStrategy.DEGRADED_OUTPUT,
    ),
    FailureClass.INVALID_ARGUMENTS: (
        ReplanStrategy.ARGUMENT_REPAIR,
        ReplanStrategy.ALTERNATE_TOOL,
        ReplanStrategy.ASK_USER,
    ),
    FailureClass.INSUFFICIENT_EVIDENCE: (
        ReplanStrategy.EVIDENCE_ACQUISITION,
        ReplanStrategy.SCOPE_EXPANSION,
        ReplanStrategy.ASK_USER,
    ),
    FailureClass.BUDGET_PRESSURE: (
        ReplanStrategy.CONTEXT_COMPRESSION,
        ReplanStrategy.REDUCE_CANDIDATES,
        ReplanStrategy.DEGRADED_OUTPUT,
    ),
    FailureClass.SUBAGENT_PARTIAL_FAILURE: (
        ReplanStrategy.PARTIAL_AGGREGATION,
        ReplanStrategy.REDUCE_CANDIDATES,
        ReplanStrategy.ASK_USER,
    ),
    FailureClass.VERIFICATION_FAILURE: (
        ReplanStrategy.EVIDENCE_ACQUISITION,
        ReplanStrategy.MODEL_ESCALATION,
        ReplanStrategy.PARTIAL_AGGREGATION,
    ),
}


def classify_failure(observation: Observation) -> FailureClass:
    code = (observation.error_code or "").casefold()
    if code in _ERROR_CLASS:
        return _ERROR_CLASS[code]
    missing = " ".join(observation.missing_items).casefold()
    if "ambiguous" in missing:
        return FailureClass.AMBIGUOUS_SECTION
    if "evidence" in missing or "paper:" in missing:
        return FailureClass.INSUFFICIENT_EVIDENCE
    if "numeric_claim" in missing or "immutable_term" in missing:
        return FailureClass.VERIFICATION_FAILURE
    raise ProjectError(
        ErrorCode.INVALID_ARGUMENT,
        "Observation does not contain a supported replanning failure class",
        {"step_id": observation.step_id, "error_code": observation.error_code},
    )


class StrategyReplanner:
    MAX_REPLANS = 2

    def __init__(self, registry: RegistrySnapshot) -> None:
        self._registry = registry

    def replan(
        self,
        plan: ExecutionPlan,
        request: ReplanRequest,
    ) -> StrategyReplanOutcome:
        if request.cancelled:
            raise ProjectError(
                ErrorCode.FAILED_PRECONDITION,
                "Cancelled task cannot be replanned",
                {"failed_step_id": request.failed_step_id},
            )
        if plan.replan_count >= self.MAX_REPLANS:
            raise ProjectError(
                ErrorCode.RESOURCE_EXHAUSTED,
                "Replan limit reached",
                {"failed_step_id": request.failed_step_id},
            )
        step = next(
            (item for item in plan.steps if item.step_id == request.failed_step_id),
            None,
        )
        if step is None:
            raise ProjectError(
                ErrorCode.NOT_FOUND,
                "Replan target step does not exist",
                {"failed_step_id": request.failed_step_id},
            )
        failure = request.failure_class or classify_failure(request.observation)
        fingerprint = _fingerprint(failure, request)
        strategy = self._select_strategy(step, failure, fingerprint, request)
        changes = self._strategy_changes(step, strategy, request)
        reason = _PUBLIC_REASONS[strategy]
        attempt = StrategyAttempt(
            failure_class=failure,
            failed_step_id=step.step_id,
            strategy=strategy,
            fingerprint=fingerprint,
        )
        patch = PlanPatch(
            patch_id=f"replan-{uuid4().hex}",
            base_plan_id=plan.plan_id,
            base_version=plan.version,
            reason_summary=reason,
            trigger_observation=request.observation,
            operations=[
                PlanPatchOperation(
                    operation="update",
                    step_id=step.step_id,
                    changes=changes,
                )
            ],
        )
        return StrategyReplanOutcome(
            strategy=strategy,
            public_reason=reason,
            attempt=attempt,
            patch=patch,
        )

    def _select_strategy(
        self,
        step: PlanStep,
        failure: FailureClass,
        fingerprint: str,
        request: ReplanRequest,
    ) -> ReplanStrategy:
        attempted = {
            attempt.strategy
            for attempt in request.strategy_history
            if attempt.fingerprint == fingerprint
            and attempt.failed_step_id == step.step_id
        }
        for strategy in _CANDIDATES[failure]:
            if strategy in attempted:
                continue
            if strategy is ReplanStrategy.ALTERNATE_TOOL:
                if self._alternate_tool(step, request) is None:
                    continue
            if strategy is ReplanStrategy.EVIDENCE_ACQUISITION:
                if request.resources.remaining_tool_calls < 1 and step.tool_name is None:
                    continue
            return strategy
        raise ProjectError(
            ErrorCode.FAILED_PRECONDITION,
            "No unused permitted replanning strategy remains",
            {"failed_step_id": step.step_id, "failure_class": failure.value},
        )

    def _strategy_changes(
        self,
        step: PlanStep,
        strategy: ReplanStrategy,
        request: ReplanRequest,
    ) -> dict[str, object]:
        marker = f"strategy:{strategy.value}"
        input_refs = list(dict.fromkeys([*step.input_refs, marker]))
        changes: dict[str, object] = {"input_refs": input_refs}
        if strategy is ReplanStrategy.QUERY_REWRITE:
            changes["action"] = f"Rewrite the query, then {step.action.casefold()}"
        elif strategy is ReplanStrategy.SCOPE_EXPANSION:
            changes["action"] = f"Expand the evidence scope, then {step.action.casefold()}"
        elif strategy is ReplanStrategy.ALTERNATE_TOOL:
            alternate = self._alternate_tool(step, request)
            assert alternate is not None
            changes.update(
                action=f"Use alternate Tool {alternate}",
                tool_name=alternate,
                step_type=StepType.TOOL_CALL,
            )
        elif strategy is ReplanStrategy.ARGUMENT_REPAIR:
            changes["action"] = f"Repair arguments against Tool schema, then {step.action.casefold()}"
        elif strategy is ReplanStrategy.EVIDENCE_ACQUISITION:
            changes["action"] = f"Acquire additional evidence, then {step.action.casefold()}"
        elif strategy is ReplanStrategy.CONTEXT_COMPRESSION:
            changes["action"] = f"Compress context before {step.action.casefold()}"
            changes["budget"] = _bounded_budget(step.budget, request.resources)
        elif strategy is ReplanStrategy.REDUCE_CANDIDATES:
            changes["action"] = f"Reduce candidates before {step.action.casefold()}"
            changes["budget"] = _bounded_budget(step.budget, request.resources)
        elif strategy is ReplanStrategy.ASK_USER:
            changes.update(
                action="Ask the user to resolve the ambiguous or missing input",
                step_type=StepType.ASK_USER,
                skill_name=None,
                tool_name=None,
                subagent_name=None,
                budget=_bounded_budget(step.budget, request.resources, clear_calls=True),
            )
        elif strategy is ReplanStrategy.MODEL_ESCALATION:
            changes.update(
                action=f"Escalate model profile and {step.action.casefold()}",
                step_type=StepType.GENERATE,
                skill_name=None,
                tool_name=None,
                subagent_name=None,
                budget=_bounded_budget(step.budget, request.resources, clear_calls=True),
            )
        elif strategy is ReplanStrategy.PARTIAL_AGGREGATION:
            changes.update(
                action="Aggregate available evidence and label unavailable portions",
                step_type=StepType.AGGREGATE,
                skill_name=None,
                tool_name=None,
                subagent_name=None,
                budget=_bounded_budget(step.budget, request.resources, clear_calls=True),
            )
        else:
            changes.update(
                action="Produce a bounded partial result with explicit limitations",
                step_type=StepType.GENERATE,
                skill_name=None,
                tool_name=None,
                subagent_name=None,
                budget=_bounded_budget(step.budget, request.resources, clear_calls=True),
            )
        return changes

    def _alternate_tool(
        self,
        step: PlanStep,
        request: ReplanRequest,
    ) -> str | None:
        if step.tool_name is None or request.resources.remaining_tool_calls < 1:
            return None
        permitted = self._registry.permitted_tools
        candidates = request.alternate_tools.get(step.tool_name, [])
        return next(
            (
                name
                for name in candidates
                if name != step.tool_name
                and name in self._registry.tools
                and (permitted is None or name in permitted)
            ),
            None,
        )


def _bounded_budget(
    current: StepBudget,
    resources: ReplanResources,
    *,
    clear_calls: bool = False,
) -> StepBudget:
    return StepBudget(
        max_tokens=min(current.max_tokens, resources.remaining_tokens),
        max_tool_calls=(
            0
            if clear_calls
            else min(current.max_tool_calls, resources.remaining_tool_calls)
        ),
        max_subagent_calls=(
            0
            if clear_calls
            else min(current.max_subagent_calls, resources.remaining_subagent_calls)
        ),
        timeout_ms=current.timeout_ms,
    )


def _fingerprint(failure: FailureClass, request: ReplanRequest) -> str:
    payload = {
        "failure_class": failure.value,
        "failed_step_id": request.failed_step_id,
        "error_code": request.observation.error_code,
        "missing_items": sorted(request.observation.missing_items),
        "quality_signal": request.observation.quality_signal,
        "data_ref": request.observation.data_ref,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


_PUBLIC_REASONS: dict[ReplanStrategy, str] = {
    ReplanStrategy.QUERY_REWRITE: "Retrieval was empty; rewrite the query before another bounded attempt.",
    ReplanStrategy.SCOPE_EXPANSION: "The current scope is insufficient; expand it within the existing budget.",
    ReplanStrategy.ALTERNATE_TOOL: "The primary Tool failed; switch to a permitted alternate Tool.",
    ReplanStrategy.MODEL_ESCALATION: "The current execution path is insufficient; use the permitted larger model profile.",
    ReplanStrategy.EVIDENCE_ACQUISITION: "Completion checks found missing support; acquire additional evidence.",
    ReplanStrategy.PARTIAL_AGGREGATION: "Some branches failed; aggregate usable results and label missing portions.",
    ReplanStrategy.ASK_USER: "Required scope or input is ambiguous; request a user decision.",
    ReplanStrategy.ARGUMENT_REPAIR: "Tool arguments violate the public schema; rebuild them from the contract.",
    ReplanStrategy.CONTEXT_COMPRESSION: "Remaining budget is constrained; compress context before continuing.",
    ReplanStrategy.REDUCE_CANDIDATES: "Remaining budget is constrained; reduce candidate breadth.",
    ReplanStrategy.DEGRADED_OUTPUT: "Resources are insufficient; return a bounded partial result with limitations.",
}
