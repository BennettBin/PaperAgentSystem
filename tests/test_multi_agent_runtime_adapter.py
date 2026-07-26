from __future__ import annotations

from pathlib import Path

import pytest

from backend.agent_runtime.unified import RuntimeRequest
from backend.core.domain.blackboard import (
    BlackboardEntry,
    BlackboardEntryKind,
    EvidenceSource,
)
from backend.infrastructure.fake.blackboard import InMemoryBlackboardRepository
from backend.subagents.coordinator import RoleAssignment, RoleRunResult
from backend.subagents.protocol import AgentRole, RoleProtocolRegistry
from backend.subagents.runtime_adapter import MultiAgentRuntimeAdapter


class BlackboardRoleRunner:
    def __init__(
        self,
        workspace_id: str,
        task_id: str,
        calls: list[RoleAssignment],
    ) -> None:
        self.workspace_id = workspace_id
        self.task_id = task_id
        self.calls = calls

    async def invoke(
        self,
        assignment: RoleAssignment,
        *,
        idempotency_key: str,
    ) -> RoleRunResult:
        self.calls.append(assignment)
        output = {
            AgentRole.PAPER_READER: {
                "paper_card_refs": [
                    f"blackboard://{self.task_id}/{assignment.assignment_id}"
                ],
                "unreadable_refs": [],
            },
            AgentRole.EVIDENCE: {
                "evidence_bundle_ref": f"blackboard://{self.task_id}/evidence",
                "unsupported_claim_refs": [],
            },
            AgentRole.CRITIC: {
                "critique_ref": f"blackboard://{self.task_id}/critic",
                "blocking_issue_refs": [],
            },
            AgentRole.WRITER: {
                "draft_ref": f"blackboard://{self.task_id}/writer",
                "citation_refs": ["artifact://citation/E1"],
            },
            AgentRole.VERIFIER: {
                "verification_ref": f"blackboard://{self.task_id}/verifier",
                "status": "passed",
            },
        }[assignment.role]
        entry = self._entry(assignment)
        return RoleRunResult(
            output=output,
            token_usage=10,
            blackboard_entries=[entry],
        )

    def _entry(self, assignment: RoleAssignment) -> BlackboardEntry:
        kinds = {
            AgentRole.PAPER_READER: BlackboardEntryKind.PAPER_CARD,
            AgentRole.EVIDENCE: BlackboardEntryKind.EVIDENCE,
            AgentRole.CRITIC: BlackboardEntryKind.GAP,
            AgentRole.WRITER: BlackboardEntryKind.DRAFT_SECTION,
            AgentRole.VERIFIER: BlackboardEntryKind.VERIFICATION_RESULT,
        }
        payloads = {
            AgentRole.PAPER_READER: {"paper_id": assignment.paper_ids[0]},
            AgentRole.EVIDENCE: {"claims": [{"citation_id": "E1"}]},
            AgentRole.CRITIC: {"issues": []},
            AgentRole.WRITER: {
                "answer": "两篇论文采用不同的方法 [E1]",
                "citation_ids": ["E1"],
            },
            AgentRole.VERIFIER: {"status": "passed", "findings": []},
        }
        return BlackboardEntry(
            entry_id=assignment.assignment_id,
            workspace_id=self.workspace_id,
            task_id=self.task_id,
            kind=kinds[assignment.role],
            producer_role=assignment.role.value,
            confidence=1.0,
            payload=payloads[assignment.role],
            source=EvidenceSource(
                file_id=(
                    assignment.paper_ids[0]
                    if assignment.role is AgentRole.PAPER_READER
                    else None
                ),
                inferred=assignment.role is not AgentRole.PAPER_READER,
            ),
        )


class RevisionRoleRunner(BlackboardRoleRunner):
    async def invoke(
        self,
        assignment: RoleAssignment,
        *,
        idempotency_key: str,
    ) -> RoleRunResult:
        if assignment.assignment_id not in {"writer:revision", "verifier:revision"}:
            result = await super().invoke(
                assignment,
                idempotency_key=idempotency_key,
            )
            if assignment.role is not AgentRole.VERIFIER:
                return result
            failed_entry = result.blackboard_entries[0].model_copy(
                update={
                    "payload": {
                        "status": "failed",
                        "findings": [
                            {
                                "severity": "severe",
                                "description": "关键结论缺少第二篇论文证据",
                            }
                        ],
                    }
                }
            )
            return result.model_copy(
                update={
                    "output": {
                        "verification_ref": (
                            f"blackboard://{self.task_id}/verifier"
                        ),
                        "status": "failed",
                    },
                    "blackboard_entries": [failed_entry],
                }
            )
        self.calls.append(assignment)
        if assignment.role is AgentRole.WRITER:
            entry = BlackboardEntry(
                entry_id="writer:revision",
                workspace_id=self.workspace_id,
                task_id=self.task_id,
                kind=BlackboardEntryKind.DRAFT_SECTION,
                producer_role=AgentRole.WRITER.value,
                confidence=1.0,
                payload={
                    "answer": "修订后比较结论 [E1][E2]",
                    "citation_ids": ["E1", "E2"],
                },
                source=EvidenceSource(inferred=True),
            )
            return RoleRunResult(
                output={
                    "draft_ref": (
                        f"blackboard://{self.task_id}/writer:revision"
                    ),
                    "citation_refs": [
                        "artifact://citation/E1",
                        "artifact://citation/E2",
                    ],
                },
                token_usage=10,
                blackboard_entries=[entry],
            )
        entry = BlackboardEntry(
            entry_id="verifier:revision",
            workspace_id=self.workspace_id,
            task_id=self.task_id,
            kind=BlackboardEntryKind.VERIFICATION_RESULT,
            producer_role=AgentRole.VERIFIER.value,
            confidence=1.0,
            payload={"status": "passed", "findings": []},
            source=EvidenceSource(inferred=True),
        )
        return RoleRunResult(
            output={
                "verification_ref": (
                    f"blackboard://{self.task_id}/verifier:revision"
                ),
                "status": "passed",
            },
            token_usage=10,
            blackboard_entries=[entry],
        )


@pytest.mark.asyncio
async def test_adapter_executes_existing_role_dag_and_returns_verified_result() -> None:
    registry = RoleProtocolRegistry.load(Path("backend/subagents/roles"))
    board = InMemoryBlackboardRepository()
    calls: list[RoleAssignment] = []
    progress: list[dict[str, object]] = []
    adapter = MultiAgentRuntimeAdapter(
        registry=registry,
        blackboard_factory=lambda: board,
        runner_factory=lambda context: BlackboardRoleRunner(
            context.workspace_id,
            context.task_id,
            calls,
        ),
        progress_sink=progress.append,
    )

    result = await adapter.execute(
        RuntimeRequest(
            task_id="task-1",
            workspace_id="ws-1",
            conversation_id="conversation-1",
            question="比较两篇论文",
            file_ids=["paper-a", "paper-b"],
        )
    )

    assert result.answer.endswith("[E1]")
    assert result.citation_ids == ["E1"]
    assert result.agent_roles == [
        "coordinator",
        "paper_reader",
        "evidence",
        "critic",
        "writer",
        "verifier",
    ]
    assert len([call for call in calls if call.role is AgentRole.PAPER_READER]) == 2
    assert {
        call.requested_tokens
        for call in calls
        if call.role is AgentRole.PAPER_READER
    } == {6000}
    assert result.subagent_run_ids == [
        "reader:paper-a",
        "reader:paper-b",
        "evidence",
        "critic",
        "writer",
        "verifier",
    ]
    entries = await board.list_active("ws-1", "task-1")
    assert set(result.blackboard_entry_ids) == {entry.entry_id for entry in entries}
    assert [event["type"] for event in progress] == [
        "multi_agent_started",
        "coordinator_agent_started",
        "coordinator_agent_completed",
        "multi_agent_completed",
    ]


@pytest.mark.asyncio
async def test_adapter_allows_exactly_one_writer_verifier_revision() -> None:
    registry = RoleProtocolRegistry.load(Path("backend/subagents/roles"))
    board = InMemoryBlackboardRepository()
    calls: list[RoleAssignment] = []
    adapter = MultiAgentRuntimeAdapter(
        registry=registry,
        blackboard_factory=lambda: board,
        runner_factory=lambda context: RevisionRoleRunner(
            context.workspace_id,
            context.task_id,
            calls,
        ),
    )

    result = await adapter.execute(
        RuntimeRequest(
            task_id="task-revision",
            workspace_id="ws-1",
            conversation_id="conversation-1",
            question="比较两篇论文",
            file_ids=["paper-a", "paper-b"],
        )
    )

    assert result.answer == "修订后比较结论 [E1][E2]"
    assert result.citation_ids == ["E1", "E2"]
    assert result.revision_rounds == 1
    assert [call.assignment_id for call in calls].count("writer:revision") == 1
    assert [call.assignment_id for call in calls].count("verifier:revision") == 1


@pytest.mark.asyncio
async def test_adapter_replays_verified_blackboard_result_without_duplicate_runs() -> None:
    registry = RoleProtocolRegistry.load(Path("backend/subagents/roles"))
    board = InMemoryBlackboardRepository()
    calls: list[RoleAssignment] = []
    adapter = MultiAgentRuntimeAdapter(
        registry=registry,
        blackboard_factory=lambda: board,
        runner_factory=lambda context: BlackboardRoleRunner(
            context.workspace_id,
            context.task_id,
            calls,
        ),
    )
    request = RuntimeRequest(
        task_id="task-replay",
        workspace_id="ws-1",
        conversation_id="conversation-1",
        question="比较两篇论文",
        file_ids=["paper-a", "paper-b"],
    )

    first = await adapter.execute(request)
    call_count = len(calls)
    replayed = await adapter.execute(request)

    assert replayed.answer == first.answer
    assert replayed.citation_ids == first.citation_ids
    assert len(calls) == call_count
