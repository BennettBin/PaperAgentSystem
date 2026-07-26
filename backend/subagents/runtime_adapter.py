"""Production boundary between UnifiedAgentRuntime and bounded role coordination."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from time import monotonic

from backend.agent_runtime.planner import (
    CompletionPredicate,
    PlanStep,
    StepBudget,
    StepType,
)
from backend.agent_runtime.unified import (
    AdvancedEvidence,
    AdvancedRuntimeResult,
    RuntimeRequest,
)
from backend.core.domain.blackboard import BlackboardEntry, BlackboardEntryKind
from backend.core.errors import ErrorCode, ProjectError
from backend.core.ports.blackboard import BlackboardRepository
from backend.core.ports.observability import TraceWriter
from backend.subagents.coordinator import (
    CoordinationBudget,
    CoordinationStatus,
    Coordinator,
    RoleAssignment,
    RoleRunner,
)
from backend.subagents.protocol import AgentRole, RoleProtocolRegistry
from backend.subagents.role_runner import RoleExecutionContext

BlackboardFactory = Callable[[], BlackboardRepository]
RunnerFactory = Callable[[RoleExecutionContext], RoleRunner]
ProgressSink = Callable[[dict[str, object]], None]
CancellationCheck = Callable[[str], bool]


class MultiAgentRuntimeAdapter:
    """Executes one feature-gated multi-paper task through the existing role DAG."""

    def __init__(
        self,
        *,
        registry: RoleProtocolRegistry,
        runner_factory: RunnerFactory,
        blackboard_factory: BlackboardFactory,
        budget: CoordinationBudget | None = None,
        progress_sink: ProgressSink | None = None,
        cancellation_check: CancellationCheck | None = None,
        trace_writer: TraceWriter | None = None,
    ) -> None:
        self._registry = registry
        self._runner_factory = runner_factory
        self._blackboard_factory = blackboard_factory
        self._budget = budget or CoordinationBudget(
            max_concurrency=4,
            max_worker_slots=4,
            # Supports the full per-role Manifest budgets for the normal
            # 2/5/10-paper operating range without starving each Reader.
            max_tokens=84_000,
            max_assignments=20,
        )
        self._progress = progress_sink or (lambda _: None)
        self._is_cancelled = cancellation_check or (lambda _: False)
        self._traces = trace_writer

    async def execute(self, request: RuntimeRequest) -> AdvancedRuntimeResult:
        paper_ids = list(dict.fromkeys(request.file_ids))
        if len(paper_ids) < 2:
            raise ProjectError(
                ErrorCode.FAILED_PRECONDITION,
                "Multi-Agent execution requires at least two distinct papers",
            )
        blackboard = self._blackboard_factory()
        existing_entries = await blackboard.list_active(
            request.workspace_id,
            request.task_id,
        )
        replayed = self._verified_result(existing_entries, len(paper_ids))
        if replayed is not None:
            self._emit(
                request,
                "multi_agent_idempotency_replayed",
                {"blackboard_entry_count": len(existing_entries)},
            )
            return replayed
        context = RoleExecutionContext(
            workspace_id=request.workspace_id,
            conversation_id=request.conversation_id or "",
            task_id=request.task_id,
            question=request.question,
            blackboard=blackboard,
        )
        runner = self._runner_factory(context)
        coordinator = Coordinator(
            registry=self._registry,
            runner=runner,
            budget=self._budget,
            blackboard=blackboard,
        )
        graph = coordinator.expand_spawn_step(
            self._spawn_step(len(paper_ids)),
            paper_ids,
        )
        self._emit(
            request,
            "multi_agent_started",
            {"paper_count": len(paper_ids), "assignment_count": len(graph.assignments)},
        )
        self._emit(
            request,
            "coordinator_agent_started",
            {"paper_count": len(paper_ids)},
        )
        cancellation = asyncio.Event()
        if self._is_cancelled(request.task_id):
            cancellation.set()
        coordinator_started = monotonic()
        try:
            result = await coordinator.execute(
                request.task_id,
                request.workspace_id,
                graph,
                cancellation=cancellation,
            )
        except Exception as exc:
            self._emit(
                request,
                "coordinator_agent_failed",
                {"error_code": _error_code(exc)},
            )
            await self._trace_coordinator(
                request,
                len(paper_ids),
                len(graph.assignments),
                coordinator_started,
                error=str(exc),
            )
            raise
        self._emit(
            request,
            "coordinator_agent_completed",
            {
                "status": result.status.value,
                "assignment_count": len(graph.assignments),
            },
        )
        await self._trace_coordinator(
            request,
            len(paper_ids),
            len(graph.assignments),
            coordinator_started,
        )
        if self._is_cancelled(request.task_id):
            cancellation.set()
        if cancellation.is_set() or result.status is CoordinationStatus.CANCELLED:
            raise ProjectError(
                ErrorCode.INVALID_STATE,
                "Multi-Agent task was cancelled",
            )
        if result.status is CoordinationStatus.FAILED:
            self._emit(
                request,
                "multi_agent_failed",
                {
                    "roles": [
                        record.role.value for record in result.failed
                    ]
                },
            )
            raise ProjectError(
                ErrorCode.GENERATION_FAILED,
                "A required multi-Agent role failed",
                {
                    "roles": [record.role.value for record in result.failed],
                    "missing_file_ids": result.missing_paper_ids,
                },
            )
        entries = await blackboard.list_active(request.workspace_id, request.task_id)
        draft_entries = [
            entry for entry in entries if entry.kind is BlackboardEntryKind.DRAFT_SECTION
        ]
        verification_entries = [
            entry
            for entry in entries
            if entry.kind is BlackboardEntryKind.VERIFICATION_RESULT
        ]
        if not draft_entries or not verification_entries:
            self._emit(
                request,
                "multi_agent_failed",
                {"reason": "missing_final_artifacts"},
            )
            raise ProjectError(
                ErrorCode.VERIFICATION_FAILED,
                "Multi-Agent execution produced no verifiable final draft",
            )
        draft = draft_entries[-1]
        verification = verification_entries[-1]
        revision_rounds = 0
        if verification.payload.get("status") != "passed":
            severe = any(
                isinstance(finding, dict)
                and finding.get("severity") == "severe"
                for finding in verification.payload.get("findings", [])
            )
            if not severe:
                self._emit(
                    request,
                    "multi_agent_failed",
                    {"reason": "verification_rejected"},
                )
                raise ProjectError(
                    ErrorCode.VERIFICATION_FAILED,
                    "Multi-Agent Verifier rejected the final draft",
                    {"findings": verification.payload.get("findings", [])},
                )
            if self._is_cancelled(request.task_id):
                raise ProjectError(
                    ErrorCode.INVALID_STATE,
                    "Multi-Agent task was cancelled before revision",
                )
            self._emit(
                request,
                "multi_agent_revision_started",
                {"round": 1},
            )
            revision_records = []
            for role, assignment_id in (
                (AgentRole.WRITER, "writer:revision"),
                (AgentRole.VERIFIER, "verifier:revision"),
            ):
                manifest = self._registry.manifests[role]
                assignment = RoleAssignment(
                    assignment_id=assignment_id,
                    role=role,
                    paper_ids=paper_ids,
                    requested_tokens=manifest.budget.max_tokens,
                    timeout_seconds=manifest.budget.timeout_seconds,
                )
                role_result = await runner.invoke(
                    assignment,
                    idempotency_key=(
                        f"{request.workspace_id}:{request.task_id}:"
                        f"{assignment.assignment_id}:{role.value}:attempt:1"
                    ),
                )
                self._registry.validate_output(role, role_result.output)
                for entry in role_result.blackboard_entries:
                    if (
                        entry.workspace_id != request.workspace_id
                        or entry.task_id != request.task_id
                    ):
                        raise ProjectError(
                            ErrorCode.PERMISSION_DENIED,
                            "Role output cannot write outside its TaskWorkspace",
                        )
                    await blackboard.append(
                        entry,
                        expected_version=entry.version - 1,
                    )
                revision_records.append(assignment)
            revision_rounds = 1
            entries = await blackboard.list_active(
                request.workspace_id,
                request.task_id,
            )
            draft_entries = [
                entry
                for entry in entries
                if entry.kind is BlackboardEntryKind.DRAFT_SECTION
            ]
            verification_entries = [
                entry
                for entry in entries
                if entry.kind is BlackboardEntryKind.VERIFICATION_RESULT
            ]
            draft = next(
                entry
                for entry in draft_entries
                if entry.entry_id == "writer:revision"
            )
            verification = next(
                entry
                for entry in verification_entries
                if entry.entry_id == "verifier:revision"
            )
            if verification.payload.get("status") != "passed":
                self._emit(
                    request,
                    "multi_agent_failed",
                    {"reason": "revision_verification_rejected"},
                )
                raise ProjectError(
                    ErrorCode.VERIFICATION_FAILED,
                    "Multi-Agent Verifier rejected the only allowed revision",
                    {"findings": verification.payload.get("findings", [])},
                )
            self._emit(
                request,
                "multi_agent_revision_completed",
                {"round": 1, "status": "passed"},
            )
        answer = str(draft.payload.get("answer", "")).strip()
        citation_ids = [
            str(value)
            for value in draft.payload.get("citation_ids", [])
            if str(value).strip()
        ]
        if not answer or not citation_ids:
            raise ProjectError(
                ErrorCode.INSUFFICIENT_EVIDENCE,
                "Multi-Agent final draft is missing answer text or citations",
            )
        roles = [AgentRole.COORDINATOR.value]
        roles.extend(record.role.value for record in result.completed)
        revision_ids = (
            ["writer:revision", "verifier:revision"]
            if revision_rounds
            else []
        )
        completion_event = (
            "multi_agent_degraded"
            if result.status is CoordinationStatus.DEGRADED
            else "multi_agent_completed"
        )
        self._emit(
            request,
            completion_event,
            {
                "status": result.status.value,
                "roles": list(dict.fromkeys(roles)),
                "missing_file_ids": result.missing_paper_ids,
            },
        )
        return AdvancedRuntimeResult(
            answer=answer,
            citation_ids=citation_ids,
            evidence=self._extract_evidence(entries, set(citation_ids)),
            public_steps=[
                "已完成任务分解",
                f"已并行读取 {len(paper_ids)} 篇论文",
                "已建立证据矩阵",
                "已完成审阅、写作和核验",
            ],
            agent_roles=list(dict.fromkeys(roles)),
            subagent_run_ids=[
                record.assignment_id for record in result.completed
            ]
            + revision_ids,
            blackboard_entry_ids=[entry.entry_id for entry in entries],
            degraded=result.status is CoordinationStatus.DEGRADED,
            revision_rounds=revision_rounds,
            missing_file_ids=result.missing_paper_ids,
        )

    @staticmethod
    def _verified_result(
        entries: list[BlackboardEntry],
        paper_count: int,
    ) -> AdvancedRuntimeResult | None:
        drafts = [
            entry
            for entry in entries
            if entry.kind is BlackboardEntryKind.DRAFT_SECTION
        ]
        passed = [
            entry
            for entry in entries
            if entry.kind is BlackboardEntryKind.VERIFICATION_RESULT
            and entry.payload.get("status") == "passed"
        ]
        if not drafts or not passed:
            return None
        draft = drafts[-1]
        answer = str(draft.payload.get("answer", "")).strip()
        citation_ids = [
            str(value)
            for value in draft.payload.get("citation_ids", [])
            if str(value).strip()
        ]
        if not answer or not citation_ids:
            return None
        roles = [AgentRole.COORDINATOR.value]
        roles.extend(entry.producer_role for entry in entries)
        return AdvancedRuntimeResult(
            answer=answer,
            citation_ids=citation_ids,
            evidence=MultiAgentRuntimeAdapter._extract_evidence(
                entries,
                set(citation_ids),
            ),
            public_steps=[
                "已复用通过核验的多 Agent 结果",
                f"已覆盖 {paper_count} 篇论文",
            ],
            agent_roles=list(dict.fromkeys(roles)),
            subagent_run_ids=[entry.entry_id for entry in entries],
            blackboard_entry_ids=[entry.entry_id for entry in entries],
            revision_rounds=int(
                any(entry.entry_id == "writer:revision" for entry in entries)
            ),
        )

    @staticmethod
    def _extract_evidence(
        entries: list[BlackboardEntry],
        citation_ids: set[str],
    ) -> list[AdvancedEvidence]:
        evidence_entries = [
            entry
            for entry in entries
            if entry.kind is BlackboardEntryKind.EVIDENCE
        ]
        if not evidence_entries:
            return []
        values: list[AdvancedEvidence] = []
        for item in evidence_entries[-1].payload.get("evidence", []):
            if (
                not isinstance(item, dict)
                or str(item.get("citation_id", "")) not in citation_ids
            ):
                continue
            try:
                values.append(
                    AdvancedEvidence(
                        id=str(item["citation_id"]),
                        file_id=str(item["paper_id"]),
                        page=int(item["page"]),
                        section=[
                            str(value) for value in item.get("section", [])
                        ],
                        quote=str(item["quote"]),
                        bbox=[
                            float(value) for value in item.get("bbox", [])
                        ],
                        source_evidence_id=str(item["source_evidence_id"]),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        return values

    def _spawn_step(self, paper_count: int) -> PlanStep:
        assignment_count = paper_count + 4
        return PlanStep(
            step_id="multi-agent:spawn",
            action="spawn_subagents",
            step_type=StepType.SUBAGENT,
            subagent_name="spawn_subagents",
            budget=StepBudget(
                max_tokens=self._budget.max_tokens,
                max_subagent_calls=min(
                    self._budget.max_assignments,
                    assignment_count,
                ),
                timeout_ms=600_000,
            ),
            completion_predicate=CompletionPredicate(
                kind="all_required_roles_terminal"
            ),
        )

    def _emit(
        self,
        request: RuntimeRequest,
        event_type: str,
        data: dict[str, object],
    ) -> None:
        self._progress(
            {
                "task_id": request.task_id,
                "type": event_type,
                "data": data,
            }
        )

    async def _trace_coordinator(
        self,
        request: RuntimeRequest,
        paper_count: int,
        assignment_count: int,
        started: float,
        *,
        error: str | None = None,
    ) -> None:
        if self._traces is None:
            return
        manifest = self._registry.manifests[AgentRole.COORDINATOR]
        await self._traces.write_trace(
            request.task_id,
            "subagent.coordinator",
            {
                "task_id": request.task_id,
                "role": AgentRole.COORDINATOR.value,
                "role_version": manifest.version,
                "model_profile": manifest.model_profile,
                "paper_count": paper_count,
                "assignment_count": assignment_count,
                "max_depth": manifest.max_depth,
            },
            duration_ms=int((monotonic() - started) * 1000),
            error=error,
        )


def _error_code(exc: Exception) -> str:
    if isinstance(exc, ProjectError):
        return exc.code.value
    return "internal_error"
