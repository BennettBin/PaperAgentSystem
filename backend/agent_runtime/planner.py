"""Versioned, fail-closed planning contracts and bounded compatibility planner."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.core.errors import ErrorCode, ProjectError


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StepType(StrEnum):
    SKILL = "skill"
    TOOL_CALL = "tool_call"
    SUBAGENT = "subagent"
    GENERATE = "generate"
    VERIFY = "verify"
    AGGREGATE = "aggregate"
    ASK_USER = "ask_user"


class EvidenceRequirement(StrEnum):
    NONE = "none"
    OPTIONAL = "optional"
    REQUIRED = "required"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ObservationStatus(StrEnum):
    COMPLETE = "complete"
    REPAIR = "repair"
    REPLAN = "replan"
    ASK_USER = "ask_user"
    FAIL = "fail"
    SKIPPED = "skipped"


class StepBudget(_StrictModel):
    max_tokens: int = Field(default=0, ge=0)
    max_tool_calls: int = Field(default=0, ge=0)
    max_subagent_calls: int = Field(default=0, ge=0)
    timeout_ms: int = Field(default=60_000, gt=0)


class PlanBudget(_StrictModel):
    max_tokens: int = Field(default=16_000, ge=0)
    max_tool_calls: int = Field(default=8, ge=0)
    max_subagent_calls: int = Field(default=2, ge=0)
    max_duration_ms: int = Field(default=600_000, gt=0)
    max_parallel_steps: int = Field(default=1, ge=1)


class CompletionPredicate(_StrictModel):
    kind: str = Field(min_length=1)
    required_fields: list[str] = Field(default_factory=list)
    minimum_evidence: int = Field(default=0, ge=0)
    minimum_quality: float | None = Field(default=None, ge=0, le=1)
    expression: str | None = None


class FallbackStrategy(_StrictModel):
    action: Literal[
        "fixed_workflow",
        "alternate_tool",
        "ask_user",
        "partial_result",
        "fail",
    ]
    target: str | None = None
    reason: str = Field(min_length=1)


class UsageRecord(_StrictModel):
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    tool_calls: int = Field(default=0, ge=0)
    subagent_calls: int = Field(default=0, ge=0)
    latency_ms: int = Field(default=0, ge=0)


class Observation(_StrictModel):
    step_id: str = Field(min_length=1)
    status: ObservationStatus
    data_ref: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    error_code: str | None = None
    retryable: bool = False
    quality_signal: dict[str, float | int | bool | str] = Field(default_factory=dict)
    usage: UsageRecord = Field(default_factory=UsageRecord)
    missing_items: list[str] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class RegistrySnapshot:
    skills: set[str]
    tools: set[str]
    subagents: set[str] = field(default_factory=set)
    permitted_tools: set[str] | None = None
    permitted_skills: set[str] | None = None
    permitted_subagents: set[str] | None = None


class PlanStep(_StrictModel):
    step_id: str = Field(min_length=1)
    action: str = Field(min_length=1)
    step_type: StepType | None = None
    skill_name: str | None = None
    tool_name: str | None = None
    subagent_name: str | None = None
    depends_on: list[str] = Field(default_factory=list)
    input_refs: list[str] = Field(default_factory=list)
    expected_output_schema: dict[str, Any] = Field(default_factory=dict)
    evidence_requirement: EvidenceRequirement = EvidenceRequirement.NONE
    budget: StepBudget = Field(default_factory=StepBudget)
    risk: RiskLevel = RiskLevel.LOW
    fallback: FallbackStrategy | None = None
    completion_predicate: CompletionPredicate | None = None
    # V1 compatibility. New writes should use completion_predicate.
    completion_condition: str = ""
    side_effect_group: str | None = None

    @model_validator(mode="after")
    def validate_step(self) -> PlanStep:
        executors = (self.skill_name, self.tool_name, self.subagent_name)
        if sum(value is not None for value in executors) > 1:
            raise ValueError("A step must invoke at most one Skill, Tool or sub Agent")
        inferred = self.step_type
        if inferred is None:
            if self.tool_name:
                inferred = StepType.TOOL_CALL
            elif self.subagent_name:
                inferred = StepType.SUBAGENT
            elif self.skill_name:
                inferred = StepType.SKILL
            else:
                inferred = StepType.GENERATE
            self.step_type = inferred
        expected_executor = {
            StepType.TOOL_CALL: self.tool_name,
            StepType.SUBAGENT: self.subagent_name,
            StepType.SKILL: self.skill_name,
        }.get(inferred)
        if inferred in {StepType.TOOL_CALL, StepType.SUBAGENT, StepType.SKILL} and not expected_executor:
            raise ValueError(f"{inferred.value} step requires its registered executor name")
        if self.completion_predicate is None:
            if not self.completion_condition.strip():
                raise ValueError("Every Plan step requires a completion predicate")
            self.completion_predicate = CompletionPredicate(
                kind="legacy_condition",
                expression=self.completion_condition.strip(),
            )
        return self


class ExecutionPlan(_StrictModel):
    schema_version: Literal["2.0"] = "2.0"
    plan_id: str = Field(default_factory=lambda: uuid4().hex, min_length=1)
    version: int = Field(default=1, ge=0)
    parent_plan_id: str | None = None
    goal: str = Field(min_length=1)
    assumptions: list[str] = Field(default_factory=list)
    global_budget: PlanBudget = Field(default_factory=PlanBudget)
    termination_condition: str = "all completion predicates are satisfied"
    steps: list[PlanStep] = Field(min_length=1, max_length=8)
    replan_count: int = Field(default=0, ge=0, le=2)

    @model_validator(mode="after")
    def require_termination(self) -> ExecutionPlan:
        if not self.termination_condition.strip():
            raise ValueError("Plan requires a termination condition")
        return self

    def topological_order(self) -> list[str]:
        ids = {step.step_id for step in self.steps}
        if len(ids) != len(self.steps):
            raise ProjectError(ErrorCode.INVALID_ARGUMENT, "Plan step IDs must be unique")
        incoming = {step.step_id: set(step.depends_on) for step in self.steps}
        if any(not deps <= ids for deps in incoming.values()):
            raise ProjectError(ErrorCode.INVALID_ARGUMENT, "Plan has an unknown dependency")
        order: list[str] = []
        while incoming:
            ready = sorted(step_id for step_id, deps in incoming.items() if not deps)
            if not ready:
                raise ProjectError(ErrorCode.INVALID_ARGUMENT, "Plan dependency graph has a cycle")
            for step_id in ready:
                order.append(step_id)
                incoming.pop(step_id)
            for deps in incoming.values():
                deps.difference_update(ready)
        return order

    def validate_against(self, registry: RegistrySnapshot) -> None:
        self.topological_order()
        token_sum = sum(step.budget.max_tokens for step in self.steps)
        tool_sum = sum(step.budget.max_tool_calls for step in self.steps)
        subagent_sum = sum(step.budget.max_subagent_calls for step in self.steps)
        if token_sum > self.global_budget.max_tokens:
            raise ProjectError(ErrorCode.RESOURCE_EXHAUSTED, "Plan token budget exceeded")
        if tool_sum > self.global_budget.max_tool_calls:
            raise ProjectError(ErrorCode.RESOURCE_EXHAUSTED, "Plan tool-call budget exceeded")
        if subagent_sum > self.global_budget.max_subagent_calls:
            raise ProjectError(ErrorCode.RESOURCE_EXHAUSTED, "Plan sub-agent budget exceeded")
        for step in self.steps:
            _validate_registered(step.skill_name, registry.skills, registry.permitted_skills, ErrorCode.SKILL_NOT_FOUND, "Skill")
            _validate_registered(step.tool_name, registry.tools, registry.permitted_tools, ErrorCode.TOOL_NOT_FOUND, "Tool")
            _validate_registered(step.subagent_name, registry.subagents, registry.permitted_subagents, ErrorCode.NOT_FOUND, "sub Agent")


class PlanPatchOperation(_StrictModel):
    operation: Literal["add", "remove", "update"]
    step_id: str = Field(min_length=1)
    step: PlanStep | None = None
    changes: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_payload(self) -> PlanPatchOperation:
        if self.operation == "add" and self.step is None:
            raise ValueError("add operation requires a step")
        if self.operation == "update" and not self.changes:
            raise ValueError("update operation requires changes")
        return self


class PlanVersionTrace(_StrictModel):
    plan_id: str
    from_version: int
    to_version: int
    reason_summary: str
    operations: list[PlanPatchOperation]
    trigger_observation: Observation


class PlanPatch(_StrictModel):
    patch_id: str = Field(min_length=1)
    base_plan_id: str = Field(min_length=1)
    base_version: int = Field(ge=0)
    reason_summary: str = Field(min_length=1)
    trigger_observation: Observation
    operations: list[PlanPatchOperation] = Field(min_length=1)

    def apply(
        self, plan: ExecutionPlan, registry: RegistrySnapshot
    ) -> tuple[ExecutionPlan, PlanVersionTrace]:
        if plan.plan_id != self.base_plan_id or plan.version != self.base_version:
            raise ProjectError(
                ErrorCode.FAILED_PRECONDITION, "Plan Patch base version mismatch"
            )
        by_id = {step.step_id: step.model_copy(deep=True) for step in plan.steps}
        for operation in self.operations:
            if operation.operation == "add":
                assert operation.step is not None
                if operation.step_id in by_id:
                    raise ProjectError(
                        ErrorCode.ALREADY_EXISTS, "Plan Patch adds a duplicate step"
                    )
                if operation.step.step_id != operation.step_id:
                    raise ProjectError(ErrorCode.INVALID_ARGUMENT, "Plan Patch step_id mismatch")
                by_id[operation.step_id] = operation.step
            elif operation.operation == "remove":
                if operation.step_id not in by_id:
                    raise ProjectError(ErrorCode.NOT_FOUND, "Plan Patch removes an unknown step")
                by_id.pop(operation.step_id)
            else:
                current = by_id.get(operation.step_id)
                if current is None:
                    raise ProjectError(ErrorCode.NOT_FOUND, "Plan Patch updates an unknown step")
                payload = current.model_dump(mode="python")
                payload.update(operation.changes)
                by_id[operation.step_id] = PlanStep.model_validate(payload)
        payload = plan.model_dump(mode="python")
        payload.update(
            {
                "version": plan.version + 1,
                "parent_plan_id": plan.plan_id,
                "replan_count": plan.replan_count + 1,
                "steps": list(by_id.values()),
            }
        )
        revised = ExecutionPlan.model_validate(payload)
        revised.validate_against(registry)
        trace = PlanVersionTrace(
            plan_id=plan.plan_id,
            from_version=plan.version,
            to_version=revised.version,
            reason_summary=self.reason_summary,
            operations=self.operations,
            trigger_observation=self.trigger_observation,
        )
        return revised, trace


def migrate_plan_v1(payload: dict[str, Any], *, plan_id: str | None = None) -> ExecutionPlan:
    """Read historical V1 plans and explicitly upgrade them to the V2 contract."""

    if payload.get("schema_version") == "2.0":
        return ExecutionPlan.model_validate(payload)
    steps: list[PlanStep] = []
    for item in payload.get("steps", []):
        step = dict(item)
        condition = str(step.get("completion_condition", "")).strip()
        step["completion_condition"] = condition
        step["completion_predicate"] = {
            "kind": "legacy_condition",
            "expression": condition,
        }
        steps.append(PlanStep.model_validate(step))
    return ExecutionPlan(
        plan_id=plan_id or str(payload.get("plan_id") or uuid4().hex),
        version=int(payload.get("version", 1)),
        parent_plan_id=payload.get("parent_plan_id"),
        goal=str(payload["goal"]),
        assumptions=list(payload.get("assumptions", [])),
        termination_condition=str(
            payload.get("termination_condition", "all completion predicates are satisfied")
        ),
        steps=steps,
        replan_count=int(payload.get("replan_count", 0)),
    )


class Planner:
    MAX_REPLANS = 2

    def __init__(self, registry: RegistrySnapshot) -> None:
        self._registry = registry

    def create(self, goal: str, skill_name: str, tool_names: list[str]) -> ExecutionPlan:
        steps = [
            PlanStep(
                step_id="skill-1",
                action=f"Apply {skill_name}",
                skill_name=skill_name,
                completion_condition="Skill input and output contract are satisfied",
            )
        ]
        previous = "skill-1"
        for index, tool_name in enumerate(tool_names, start=1):
            step_id = f"tool-{index}"
            steps.append(
                PlanStep(
                    step_id=step_id,
                    action=f"Run {tool_name}",
                    tool_name=tool_name,
                    depends_on=[previous],
                    completion_condition=f"{tool_name} returns a valid structured result",
                )
            )
            previous = step_id
        plan = ExecutionPlan(goal=goal, steps=steps)
        plan.validate_against(self._registry)
        return plan

    def replan(
        self, plan: ExecutionPlan, *, failed_step_id: str, reason: str
    ) -> ExecutionPlan:
        if plan.replan_count >= self.MAX_REPLANS:
            raise ProjectError(
                ErrorCode.RESOURCE_EXHAUSTED,
                "Replan limit reached",
                {"failed_step_id": failed_step_id, "reason": reason},
            )
        replacement = plan.model_copy(deep=True)
        replacement.version += 1
        replacement.parent_plan_id = plan.plan_id
        replacement.replan_count += 1
        for step in replacement.steps:
            if step.step_id == failed_step_id:
                step.action = f"{step.action} (retry after: {reason})"
        replacement.validate_against(self._registry)
        return replacement


def _validate_registered(
    value: str | None,
    registered: set[str],
    permitted: set[str] | None,
    code: ErrorCode,
    label: str,
) -> None:
    if value is None:
        return
    if value not in registered:
        raise ProjectError(code, f"Unregistered {label}: {value}")
    if permitted is not None and value not in permitted:
        raise ProjectError(ErrorCode.PERMISSION_DENIED, f"Forbidden {label}: {value}")
