"""Budgeted role DAG expansion and bounded multi-Agent coordination."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.agent_runtime.planner import PlanStep, StepType
from backend.core.domain.blackboard import BlackboardEntry
from backend.core.errors import ErrorCode, ProjectError
from backend.core.ports.blackboard import BlackboardRepository
from backend.subagents.protocol import AgentRole, RoleProtocolRegistry


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CoordinationStatus(StrEnum):
    COMPLETED = "completed"
    DEGRADED = "degraded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CoordinationBudget(_StrictModel):
    max_concurrency: int = Field(ge=1)
    max_worker_slots: int = Field(ge=1)
    max_tokens: int = Field(ge=0)
    max_assignments: int = Field(ge=1)


class RoleAssignment(_StrictModel):
    assignment_id: str = Field(min_length=1)
    role: AgentRole
    paper_ids: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    requested_tokens: int = Field(ge=0)
    timeout_seconds: int = Field(gt=0)
    depth: int = Field(default=1, ge=1, le=1)


class CoordinationGraph(_StrictModel):
    assignments: list[RoleAssignment] = Field(min_length=1)

    @model_validator(mode="after")
    def valid_dag(self) -> CoordinationGraph:
        ids = {item.assignment_id for item in self.assignments}
        if len(ids) != len(self.assignments):
            raise ValueError("Coordination assignment IDs must be unique")
        incoming = {item.assignment_id: set(item.depends_on) for item in self.assignments}
        if any(not dependencies <= ids for dependencies in incoming.values()):
            raise ValueError("Coordination graph contains an unknown dependency")
        while incoming:
            ready = {key for key, value in incoming.items() if not value}
            if not ready:
                raise ValueError("Coordination graph contains a cycle")
            for key in ready:
                incoming.pop(key)
            for value in incoming.values():
                value.difference_update(ready)
        return self


class RoleRunResult(_StrictModel):
    output: dict[str, Any]
    token_usage: int = Field(default=0, ge=0)
    blackboard_entries: list[BlackboardEntry] = Field(default_factory=list)


class RoleRunRecord(_StrictModel):
    assignment_id: str
    role: AgentRole
    paper_ids: list[str]
    output: dict[str, Any] | None = None
    token_usage: int = 0
    error: str | None = None


class CoordinationResult(_StrictModel):
    status: CoordinationStatus
    completed: list[RoleRunRecord]
    failed: list[RoleRunRecord]
    cancelled_assignment_ids: list[str] = Field(default_factory=list)
    missing_paper_ids: list[str] = Field(default_factory=list)
    total_tokens: int = Field(ge=0)


class RoleRunner(Protocol):
    async def invoke(
        self, assignment: RoleAssignment, *, idempotency_key: str
    ) -> RoleRunResult: ...


class Coordinator:
    def __init__(
        self,
        *,
        registry: RoleProtocolRegistry,
        runner: RoleRunner,
        budget: CoordinationBudget,
        blackboard: BlackboardRepository | None = None,
    ) -> None:
        self._registry = registry
        self._runner = runner
        self._budget = budget
        self._blackboard = blackboard

    def expand_spawn_step(
        self, step: PlanStep, paper_ids: Sequence[str]
    ) -> CoordinationGraph:
        if step.step_type is not StepType.SUBAGENT or step.action != "spawn_subagents":
            raise ProjectError(
                ErrorCode.INVALID_ARGUMENT, "Coordinator requires a spawn_subagents Plan step"
            )
        unique_papers = list(dict.fromkeys(paper_ids))
        if not unique_papers:
            raise ProjectError(ErrorCode.MISSING_REQUIRED_FIELD, "No papers to assign")
        assignment_count = len(unique_papers) + 4
        allowed_count = min(self._budget.max_assignments, step.budget.max_subagent_calls)
        if assignment_count > allowed_count:
            raise ProjectError(
                ErrorCode.RESOURCE_EXHAUSTED, "Coordination assignment budget exceeded"
            )
        fair_tokens = min(
            step.budget.max_tokens // assignment_count,
            self._budget.max_tokens // assignment_count,
        )
        reader_ids = [f"reader:{paper_id}" for paper_id in unique_papers]
        assignments = [
            self._assignment(
                assignment_id=assignment_id,
                role=AgentRole.PAPER_READER,
                paper_ids=[paper_id],
                depends_on=[],
                tokens=fair_tokens,
            )
            for assignment_id, paper_id in zip(reader_ids, unique_papers, strict=True)
        ]
        assignments.extend(
            [
                self._assignment("evidence", AgentRole.EVIDENCE, unique_papers, reader_ids, fair_tokens),
                self._assignment("critic", AgentRole.CRITIC, unique_papers, ["evidence"], fair_tokens),
                self._assignment(
                    "writer", AgentRole.WRITER, unique_papers, ["evidence", "critic"], fair_tokens
                ),
                self._assignment("verifier", AgentRole.VERIFIER, unique_papers, ["writer"], fair_tokens),
            ]
        )
        return CoordinationGraph(assignments=assignments)

    async def execute(
        self,
        task_id: str,
        workspace_id: str,
        graph: CoordinationGraph,
        *,
        cancellation: asyncio.Event | None = None,
    ) -> CoordinationResult:
        cancellation = cancellation or asyncio.Event()
        terminal: dict[str, RoleRunRecord] = {}
        cancelled: list[str] = []
        total_tokens = 0
        concurrency = min(self._budget.max_concurrency, self._budget.max_worker_slots)
        while len(terminal) + len(cancelled) < len(graph.assignments):
            remaining = [item for item in graph.assignments if item.assignment_id not in terminal and item.assignment_id not in cancelled]
            if cancellation.is_set():
                cancelled.extend(item.assignment_id for item in remaining)
                break
            ready = [item for item in remaining if set(item.depends_on) <= set(terminal)]
            if not ready:
                raise ProjectError(ErrorCode.INVALID_STATE, "Coordination DAG made no progress")
            blocked = [
                item
                for item in ready
                if self._has_failed_required_dependency(item, terminal)
            ]
            for assignment in blocked:
                terminal[assignment.assignment_id] = RoleRunRecord(
                    assignment_id=assignment.assignment_id,
                    role=assignment.role,
                    paper_ids=assignment.paper_ids,
                    error="Required upstream role failed",
                )
            ready = [item for item in ready if item not in blocked]
            if not ready:
                continue
            for offset in range(0, len(ready), concurrency):
                batch = ready[offset : offset + concurrency]
                records = await asyncio.gather(
                    *(self._run(task_id, workspace_id, item) for item in batch)
                )
                for record in records:
                    terminal[record.assignment_id] = record
                    total_tokens += record.token_usage
                if total_tokens > self._budget.max_tokens:
                    raise ProjectError(ErrorCode.RESOURCE_EXHAUSTED, "Coordination token budget exceeded")
                if cancellation.is_set():
                    break
        completed = [record for record in terminal.values() if record.error is None]
        failed = [record for record in terminal.values() if record.error is not None]
        missing = sorted(
            paper_id
            for record in failed
            if record.role is AgentRole.PAPER_READER
            for paper_id in record.paper_ids
        )
        failed_required_role = any(
            record.role is not AgentRole.PAPER_READER
            and self._registry.manifests[record.role].failure_policy.required
            for record in failed
        )
        if cancelled:
            status = CoordinationStatus.CANCELLED
        elif failed_required_role:
            status = CoordinationStatus.FAILED
        elif failed:
            status = CoordinationStatus.DEGRADED
        else:
            status = CoordinationStatus.COMPLETED
        return CoordinationResult(
            status=status,
            completed=completed,
            failed=failed,
            cancelled_assignment_ids=sorted(cancelled),
            missing_paper_ids=missing,
            total_tokens=total_tokens,
        )

    def _has_failed_required_dependency(
        self,
        assignment: RoleAssignment,
        terminal: dict[str, RoleRunRecord],
    ) -> bool:
        for dependency_id in assignment.depends_on:
            dependency = terminal[dependency_id]
            if dependency.error is None:
                continue
            # A failed Reader is an explicitly supported partial-result path:
            # Evidence can still be built from the remaining Paper Cards.
            if dependency.role is AgentRole.PAPER_READER:
                continue
            if self._registry.manifests[dependency.role].failure_policy.required:
                return True
        return False

    async def _run(
        self, task_id: str, workspace_id: str, assignment: RoleAssignment
    ) -> RoleRunRecord:
        try:
            manifest = self._registry.manifests[assignment.role]
            attempts = (
                min(1, manifest.budget.max_retries) + 1
                if manifest.failure_policy.on_timeout == "retry_once"
                else 1
            )
            result: RoleRunResult | None = None
            for attempt in range(1, attempts + 1):
                try:
                    result = await asyncio.wait_for(
                        self._runner.invoke(
                            assignment,
                            idempotency_key=(
                                f"{workspace_id}:{task_id}:"
                                f"{assignment.assignment_id}:"
                                f"{assignment.role.value}:attempt:{attempt}"
                            ),
                        ),
                        timeout=assignment.timeout_seconds,
                    )
                    break
                except TimeoutError:
                    if attempt >= attempts:
                        raise
            if result is None:
                raise ProjectError(
                    ErrorCode.INTERNAL_ERROR,
                    "Role execution ended without a result",
                )
            self._registry.validate_output(assignment.role, result.output)
            _minimum_evidence_check(assignment.role, result.output)
            if self._blackboard:
                for entry in result.blackboard_entries:
                    if entry.workspace_id != workspace_id or entry.task_id != task_id:
                        raise ProjectError(
                            ErrorCode.PERMISSION_DENIED,
                            "Role output cannot write outside its TaskWorkspace",
                        )
                    await self._blackboard.append(entry, expected_version=entry.version - 1)
            return RoleRunRecord(
                assignment_id=assignment.assignment_id,
                role=assignment.role,
                paper_ids=assignment.paper_ids,
                output=result.output,
                token_usage=result.token_usage,
            )
        except Exception as exc:
            return RoleRunRecord(
                assignment_id=assignment.assignment_id,
                role=assignment.role,
                paper_ids=assignment.paper_ids,
                error=str(exc),
            )

    def _assignment(
        self,
        assignment_id: str,
        role: AgentRole,
        paper_ids: list[str],
        depends_on: list[str],
        tokens: int,
    ) -> RoleAssignment:
        manifest = self._registry.manifests[role]
        return RoleAssignment(
            assignment_id=assignment_id,
            role=role,
            paper_ids=paper_ids,
            depends_on=depends_on,
            requested_tokens=min(tokens, manifest.budget.max_tokens),
            timeout_seconds=manifest.budget.timeout_seconds,
        )


def _minimum_evidence_check(role: AgentRole, output: dict[str, Any]) -> None:
    required_non_empty = {
        AgentRole.PAPER_READER: "paper_card_refs",
        AgentRole.EVIDENCE: "evidence_bundle_ref",
        AgentRole.WRITER: "citation_refs",
        AgentRole.VERIFIER: "verification_ref",
    }
    field = required_non_empty.get(role)
    if field is not None and not output.get(field):
        raise ProjectError(
            ErrorCode.INSUFFICIENT_EVIDENCE,
            f"{role.value} output failed minimum evidence check",
            {"field": field},
        )
