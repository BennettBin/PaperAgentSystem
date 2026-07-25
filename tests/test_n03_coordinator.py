from __future__ import annotations

import asyncio
from pathlib import Path
from time import perf_counter

import pytest

from backend.agent_runtime.planner import CompletionPredicate, PlanStep, StepBudget, StepType
from backend.subagents.coordinator import (
    CoordinationBudget,
    CoordinationStatus,
    Coordinator,
    RoleAssignment,
    RoleRunResult,
)
from backend.subagents.protocol import AgentRole, RoleProtocolRegistry


class DelayedRoleRunner:
    def __init__(
        self,
        *,
        delay: float = 0.0,
        failed_paper: str | None = None,
        failed_role: AgentRole | None = None,
    ) -> None:
        self.delay = delay
        self.failed_paper = failed_paper
        self.failed_role = failed_role
        self.calls: list[RoleAssignment] = []
        self.active = 0
        self.max_active = 0

    async def invoke(self, assignment: RoleAssignment, *, idempotency_key: str) -> RoleRunResult:
        self.calls.append(assignment)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            if assignment.paper_ids == [self.failed_paper]:
                raise RuntimeError("reader failed")
            if assignment.role is self.failed_role:
                raise RuntimeError(f"{assignment.role.value} failed")
            output = {
                AgentRole.PAPER_READER: {
                    "paper_card_refs": [f"artifact://paper_card/{assignment.paper_ids[0]}"],
                    "unreadable_refs": [],
                },
                AgentRole.EVIDENCE: {
                    "evidence_bundle_ref": "artifact://evidence/bundle-1",
                    "unsupported_claim_refs": [],
                },
                AgentRole.CRITIC: {
                    "critique_ref": "artifact://critique/critique-1",
                    "blocking_issue_refs": [],
                },
                AgentRole.WRITER: {
                    "draft_ref": "artifact://draft/draft-1",
                    "citation_refs": ["artifact://citation/E1"],
                },
                AgentRole.VERIFIER: {
                    "verification_ref": "artifact://verification/report-1",
                    "status": "passed",
                },
            }[assignment.role]
            return RoleRunResult(output=output, token_usage=10)
        finally:
            self.active -= 1


def _spawn_step() -> PlanStep:
    return PlanStep(
        step_id="spawn",
        action="spawn_subagents",
        step_type=StepType.SUBAGENT,
        subagent_name="spawn_subagents",
        budget=StepBudget(max_tokens=10_000, max_subagent_calls=20, timeout_ms=10_000),
        completion_predicate=CompletionPredicate(kind="all_required_roles_terminal"),
    )


def _coordinator(runner: DelayedRoleRunner, concurrency: int) -> Coordinator:
    return Coordinator(
        registry=RoleProtocolRegistry.load(Path("backend/subagents/roles")),
        runner=runner,
        budget=CoordinationBudget(
            max_concurrency=concurrency,
            max_worker_slots=concurrency,
            max_tokens=10_000,
            max_assignments=20,
        ),
    )


@pytest.mark.parametrize("paper_count", [2, 5, 10])
@pytest.mark.asyncio
async def test_dispatches_2_5_10_papers_once_with_depth_one(paper_count: int) -> None:
    runner = DelayedRoleRunner()
    coordinator = _coordinator(runner, concurrency=4)
    papers = [f"paper-{index}" for index in range(paper_count)]
    graph = coordinator.expand_spawn_step(_spawn_step(), papers + [papers[0]])
    readers = [item for item in graph.assignments if item.role is AgentRole.PAPER_READER]
    assert len(readers) == paper_count
    assert len({item.paper_ids[0] for item in readers}) == paper_count
    assert all(item.depth == 1 for item in graph.assignments)

    result = await coordinator.execute("task-1", "ws-1", graph)
    assert result.status is CoordinationStatus.COMPLETED
    assert not result.failed


@pytest.mark.asyncio
async def test_five_paper_wall_clock_is_at_least_30_percent_faster_than_serial() -> None:
    papers = [f"paper-{index}" for index in range(5)]
    serial_runner = DelayedRoleRunner(delay=0.025)
    serial = _coordinator(serial_runner, concurrency=1)
    started = perf_counter()
    await serial.execute("serial", "ws-1", serial.expand_spawn_step(_spawn_step(), papers))
    serial_seconds = perf_counter() - started

    parallel_runner = DelayedRoleRunner(delay=0.025)
    parallel = _coordinator(parallel_runner, concurrency=5)
    started = perf_counter()
    await parallel.execute("parallel", "ws-1", parallel.expand_spawn_step(_spawn_step(), papers))
    parallel_seconds = perf_counter() - started
    assert parallel_seconds <= serial_seconds * 0.70
    assert parallel_runner.max_active >= 5


@pytest.mark.asyncio
async def test_single_reader_failure_preserves_completed_results_and_labels_missing_paper() -> None:
    runner = DelayedRoleRunner(failed_paper="paper-2")
    coordinator = _coordinator(runner, concurrency=3)
    result = await coordinator.execute(
        "task-partial",
        "ws-1",
        coordinator.expand_spawn_step(_spawn_step(), ["paper-1", "paper-2", "paper-3"]),
    )
    assert result.status is CoordinationStatus.DEGRADED
    assert result.missing_paper_ids == ["paper-2"]
    assert len([item for item in result.completed if item.role is AgentRole.PAPER_READER]) == 2
    assert any(item.role is AgentRole.VERIFIER for item in result.completed)
    assert len([call for call in runner.calls if call.role is AgentRole.PAPER_READER]) == 3


@pytest.mark.asyncio
async def test_required_failure_stops_dependent_roles() -> None:
    runner = DelayedRoleRunner(failed_role=AgentRole.EVIDENCE)
    coordinator = _coordinator(runner, concurrency=3)

    result = await coordinator.execute(
        "task-required-failure",
        "ws-1",
        coordinator.expand_spawn_step(_spawn_step(), ["paper-1", "paper-2"]),
    )

    assert result.status is CoordinationStatus.FAILED
    called_roles = [call.role for call in runner.calls]
    assert AgentRole.EVIDENCE in called_roles
    assert AgentRole.CRITIC not in called_roles
    assert AgentRole.WRITER not in called_roles
    assert AgentRole.VERIFIER not in called_roles


@pytest.mark.asyncio
async def test_optional_critic_failure_degrades_but_writer_and_verifier_continue() -> None:
    runner = DelayedRoleRunner(failed_role=AgentRole.CRITIC)
    coordinator = _coordinator(runner, concurrency=3)

    result = await coordinator.execute(
        "task-critic-failure",
        "ws-1",
        coordinator.expand_spawn_step(_spawn_step(), ["paper-1", "paper-2"]),
    )

    assert result.status is CoordinationStatus.DEGRADED
    called_roles = [call.role for call in runner.calls]
    assert AgentRole.WRITER in called_roles
    assert AgentRole.VERIFIER in called_roles


def test_reuses_each_paper_read_across_roles_and_removes_at_least_80_percent_duplicates() -> None:
    runner = DelayedRoleRunner()
    coordinator = _coordinator(runner, concurrency=4)
    unique = [f"paper-{index}" for index in range(5)]
    requested = [paper for paper in unique for _ in range(5)]
    graph = coordinator.expand_spawn_step(_spawn_step(), requested)
    readers = [item for item in graph.assignments if item.role is AgentRole.PAPER_READER]
    assert len(readers) == 5
    assert 1 - len(readers) / len(requested) >= 0.80


@pytest.mark.asyncio
async def test_straggler_timeout_and_pre_dispatch_cancellation_are_explicit() -> None:
    slow_runner = DelayedRoleRunner(delay=0.05)
    coordinator = _coordinator(slow_runner, concurrency=2)
    graph = coordinator.expand_spawn_step(_spawn_step(), ["paper-1", "paper-2"])
    graph = graph.model_copy(
        update={
            "assignments": [
                item.model_copy(update={"timeout_seconds": 0.01})
                if item.role is AgentRole.PAPER_READER
                else item
                for item in graph.assignments
            ]
        }
    )
    timed_out = await coordinator.execute("timeout", "ws-1", graph)
    assert timed_out.status is CoordinationStatus.DEGRADED
    assert timed_out.missing_paper_ids == ["paper-1", "paper-2"]

    cancellation = asyncio.Event()
    cancellation.set()
    cancelled = await coordinator.execute(
        "cancelled", "ws-1", coordinator.expand_spawn_step(_spawn_step(), ["paper-1"]),
        cancellation=cancellation,
    )
    assert cancelled.status is CoordinationStatus.CANCELLED
    assert len(cancelled.cancelled_assignment_ids) == 5
