from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from backend.core.domain.blackboard import BlackboardEntryKind
from backend.core.ports.llm_client import LLMClient
from backend.infrastructure.fake.blackboard import InMemoryBlackboardRepository
from backend.subagents.coordinator import RoleAssignment
from backend.subagents.protocol import AgentRole, RoleProtocolRegistry
from backend.subagents.role_runner import (
    ProductionRoleRunner,
    RoleExecutionContext,
)
from backend.tool_runtime.runtime import ToolContext, ToolInvocationResult


class ScriptedRoleLLM(LLMClient):
    def __init__(
        self,
        requested_profiles: list[str],
        *,
        input_tokens: int = 0,
        output_tokens: int = 20,
        writer_payloads: list[dict[str, Any] | str] | None = None,
        evidence_conflict_ids: list[str] | None = None,
        critic_severity: str = "warning",
        reader_evidence_id: str | None = None,
        reader_quote: str | None = None,
        reader_empty_evidence: bool = False,
        verifier_payload: dict[str, Any] | str | None = None,
    ) -> None:
        self.requested_profiles = requested_profiles
        self.writer_payloads = list(writer_payloads or [])
        self.writer_calls = 0
        self.evidence_conflict_ids = evidence_conflict_ids or []
        self.critic_severity = critic_severity
        self.reader_evidence_id = reader_evidence_id
        self.reader_quote = reader_quote
        self.reader_empty_evidence = reader_empty_evidence
        self.verifier_payload = verifier_payload
        self.last_usage = SimpleNamespace(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
        )

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        top_p: float = 0.95,
        stop_sequences: list[str] | None = None,
    ) -> str:
        del prompt, system_prompt, max_tokens, temperature, top_p, stop_sequences
        return ""

    async def generate_with_schema(
        self,
        prompt: str,
        system_prompt: str | None = None,
        response_schema: dict[str, Any] | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.7,
    ) -> str:
        del system_prompt, response_schema, max_tokens, temperature
        if prompt.startswith("ROLE: paper_reader"):
            file_id = re.search(r"ASSIGNED_FILE_ID=([^\n]+)", prompt).group(1)  # type: ignore[union-attr]
            return json.dumps(
                {
                    "title": file_id,
                    "research_question": "研究问题",
                    "methodology": f"{file_id} 方法",
                    "datasets": [f"{file_id} 数据集"],
                    "metrics": ["Accuracy"],
                    "results": ["Accuracy 90%"],
                    "contributions": ["贡献"],
                    "limitations": ["局限"],
                    "evidence": [] if self.reader_empty_evidence else [
                        {
                            "evidence_id": (
                                self.reader_evidence_id
                                or f"{file_id}-chunk"
                            ),
                            "field": "methodology",
                            "quote": (
                                self.reader_quote
                                or f"{file_id} Accuracy 90%"
                            ),
                            "page": 1,
                        }
                    ],
                    "missing_fields": [],
                }
            )
        if prompt.startswith("ROLE: evidence"):
            return json.dumps(
                {
                    "claims": [
                        {
                            "claim_id": "C1",
                            "text": "论文 A 的结果为 90%",
                            "paper_id": "paper-a",
                            "citation_ids": ["E1"],
                            "inferred": False,
                        },
                        {
                            "claim_id": "C2",
                            "text": "论文 B 的结果为 90%",
                            "paper_id": "paper-b",
                            "citation_ids": ["E2"],
                            "inferred": False,
                        },
                    ],
                    "conflict_ids": self.evidence_conflict_ids,
                    "missing_items": [],
                }
            )
        if prompt.startswith("ROLE: critic"):
            return json.dumps(
                {
                    "issues": [
                        {
                            "issue_id": "I1",
                            "issue_type": "coverage_gap",
                            "claim_ids": ["C1"],
                            "evidence_refs": ["E1"],
                            "description": "说明比较维度",
                            "severity": self.critic_severity,
                        }
                    ]
                }
            )
        if prompt.startswith("ROLE: writer"):
            self.writer_calls += 1
            if self.writer_payloads:
                payload = self.writer_payloads[
                    min(self.writer_calls - 1, len(self.writer_payloads) - 1)
                ]
                return (
                    payload
                    if isinstance(payload, str)
                    else json.dumps(payload)
                )
            return json.dumps(
                {
                    "answer": "论文 A 与论文 B 的结果均为 90% [E1][E2]",
                    "citation_ids": ["E1", "E2"],
                    "issue_resolutions": [
                        {
                            "issue_id": "I1",
                            "status": "accepted",
                            "rationale": "已补充比较维度",
                        }
                    ],
                }
            )
        if prompt.startswith("ROLE: verifier"):
            if self.verifier_payload is not None:
                return (
                    self.verifier_payload
                    if isinstance(self.verifier_payload, str)
                    else json.dumps(self.verifier_payload)
                )
            return json.dumps({"status": "passed", "findings": []})
        raise AssertionError(f"unexpected prompt: {prompt[:40]}")


class RecordingSearchTool:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any], ToolContext]] = []

    async def invoke(
        self,
        tool_name: str,
        raw_arguments: dict[str, Any],
        context: ToolContext,
        idempotency_key: str,
    ) -> ToolInvocationResult:
        del idempotency_key
        self.calls.append((tool_name, raw_arguments, context))
        file_id = raw_arguments["file_ids"][0]
        return ToolInvocationResult(
            tool_name=tool_name,
            output={
                "hits": [
                    {
                        "chunk_id": f"{file_id}-chunk",
                        "file_id": file_id,
                        "text": f"{file_id} Accuracy 90%",
                        "section_path": ["Results"],
                        "page_start": 1,
                        "page_end": 1,
                        "bbox": [0.1, 0.1, 0.8, 0.2],
                        "score": 0.95,
                    }
                ]
            },
            data_ref=None,
            truncated=False,
            attempts=1,
        )


def _assignment(role: AgentRole, assignment_id: str, paper_ids: list[str]) -> RoleAssignment:
    return RoleAssignment(
        assignment_id=assignment_id,
        role=role,
        paper_ids=paper_ids,
        requested_tokens=1000,
        timeout_seconds=30,
    )


@pytest.mark.asyncio
async def test_builtin_roles_are_file_scoped_structured_and_traceable() -> None:
    registry = RoleProtocolRegistry.load(Path("backend/subagents/roles"))
    board = InMemoryBlackboardRepository()
    tools = RecordingSearchTool()
    profiles: list[str] = []
    llm = ScriptedRoleLLM(profiles)
    events: list[dict[str, object]] = []
    runner = ProductionRoleRunner(
        registry,
        RoleExecutionContext(
            workspace_id="ws-1",
            conversation_id="conversation-1",
            task_id="task-1",
            question="比较两篇论文",
            blackboard=board,
        ),
        llm_resolver=lambda profile: profiles.append(profile) or llm,
        tool_runtime=tools,
        progress_sink=events.append,
    )

    assignments = [
        _assignment(AgentRole.PAPER_READER, "reader:paper-a", ["paper-a"]),
        _assignment(AgentRole.PAPER_READER, "reader:paper-b", ["paper-b"]),
        _assignment(AgentRole.EVIDENCE, "evidence", ["paper-a", "paper-b"]),
        _assignment(AgentRole.CRITIC, "critic", ["paper-a", "paper-b"]),
        _assignment(AgentRole.WRITER, "writer", ["paper-a", "paper-b"]),
        _assignment(AgentRole.VERIFIER, "verifier", ["paper-a", "paper-b"]),
    ]
    for assignment in assignments:
        result = await runner.invoke(
            assignment,
            idempotency_key=f"task-1:{assignment.assignment_id}",
        )
        for entry in result.blackboard_entries:
            await board.append(entry, expected_version=0)

    assert [call[1]["file_ids"] for call in tools.calls] == [
        ["paper-a"],
        ["paper-b"],
    ]
    assert all(call[0] == "search_document" for call in tools.calls)
    assert all("search_document" in call[2].allowed_tools for call in tools.calls)
    assert profiles == [
        "paper_reader_v1",
        "paper_reader_v1",
        "evidence_v1",
        "critic_v1",
        "writer_v1",
        "verifier_v1",
    ]
    entries = await board.list_active("ws-1", "task-1")
    assert len(entries) == 6
    verification = next(
        entry
        for entry in entries
        if entry.kind is BlackboardEntryKind.VERIFICATION_RESULT
    )
    assert verification.payload["status"] == "passed"
    event_types = [event["type"] for event in events]
    assert "paper_reader_agent_started" in event_types
    assert "verifier_agent_passed" in event_types


@pytest.mark.asyncio
async def test_paper_reader_rejects_multiple_assigned_files() -> None:
    registry = RoleProtocolRegistry.load(Path("backend/subagents/roles"))
    runner = ProductionRoleRunner(
        registry,
        RoleExecutionContext(
            workspace_id="ws-1",
            conversation_id="conversation-1",
            task_id="task-1",
            question="比较",
            blackboard=InMemoryBlackboardRepository(),
        ),
        llm_resolver=lambda _: ScriptedRoleLLM([]),
        tool_runtime=RecordingSearchTool(),
    )

    with pytest.raises(Exception, match="exactly one assigned file"):
        await runner.invoke(
            _assignment(
                AgentRole.PAPER_READER,
                "reader:invalid",
                ["paper-a", "paper-b"],
            ),
            idempotency_key="task-1:reader:invalid",
        )


@pytest.mark.asyncio
async def test_paper_reader_canonicalizes_uniquely_grounded_model_evidence_id() -> None:
    registry = RoleProtocolRegistry.load(Path("backend/subagents/roles"))
    events: list[dict[str, object]] = []
    runner = ProductionRoleRunner(
        registry,
        RoleExecutionContext(
            workspace_id="ws-1",
            conversation_id="conversation-1",
            task_id="task-reader-canonical",
            question="这篇文章主要讲了什么",
            blackboard=InMemoryBlackboardRepository(),
        ),
        llm_resolver=lambda _: ScriptedRoleLLM(
            [],
            reader_evidence_id="model-invented-id",
        ),
        tool_runtime=RecordingSearchTool(),
        progress_sink=events.append,
    )

    result = await runner.invoke(
        _assignment(AgentRole.PAPER_READER, "reader:paper-a", ["paper-a"]),
        idempotency_key="task-reader-canonical:reader:paper-a",
    )

    evidence = result.blackboard_entries[0].payload["card"]["evidence"][0]
    assert evidence["evidence_id"] == "paper-a-chunk"
    assert evidence["page"] == 1
    assert any(
        event["type"] == "paper_reader_evidence_normalized"
        for event in events
    )


@pytest.mark.asyncio
async def test_paper_reader_falls_back_to_raw_hits_without_guessing_chunk_id() -> None:
    registry = RoleProtocolRegistry.load(Path("backend/subagents/roles"))
    events: list[dict[str, object]] = []
    runner = ProductionRoleRunner(
        registry,
        RoleExecutionContext(
            workspace_id="ws-1",
            conversation_id="conversation-1",
            task_id="task-reader-raw",
            question="这篇文章主要讲了什么",
            blackboard=InMemoryBlackboardRepository(),
        ),
        llm_resolver=lambda _: ScriptedRoleLLM(
            [],
            reader_evidence_id="model-invented-id",
            reader_quote="a generated paraphrase absent from every source hit",
        ),
        tool_runtime=RecordingSearchTool(),
        progress_sink=events.append,
    )

    result = await runner.invoke(
        _assignment(AgentRole.PAPER_READER, "reader:paper-a", ["paper-a"]),
        idempotency_key="task-reader-raw:reader:paper-a",
    )

    evidence = result.blackboard_entries[0].payload["card"]["evidence"]
    assert evidence == [
        {
            "evidence_id": "paper-a-chunk",
            "field": "retrieved_evidence",
            "quote": "paper-a Accuracy 90%",
            "page": 1,
        }
    ]
    normalized_event = next(
        event
        for event in events
        if event["type"] == "paper_reader_evidence_normalized"
    )
    assert normalized_event["data"]["raw_hit_fallback_used"] is True


@pytest.mark.asyncio
async def test_paper_reader_falls_back_to_raw_hits_when_model_returns_no_evidence() -> None:
    registry = RoleProtocolRegistry.load(Path("backend/subagents/roles"))
    events: list[dict[str, object]] = []
    runner = ProductionRoleRunner(
        registry,
        RoleExecutionContext(
            workspace_id="ws-1",
            conversation_id="conversation-1",
            task_id="task-reader-empty",
            question="请比较两篇文章",
            blackboard=InMemoryBlackboardRepository(),
        ),
        llm_resolver=lambda _: ScriptedRoleLLM(
            [],
            reader_empty_evidence=True,
        ),
        tool_runtime=RecordingSearchTool(),
        progress_sink=events.append,
    )

    result = await runner.invoke(
        _assignment(AgentRole.PAPER_READER, "reader:paper-a", ["paper-a"]),
        idempotency_key="task-reader-empty:reader:paper-a",
    )

    evidence = result.blackboard_entries[0].payload["card"]["evidence"]
    assert evidence == [
        {
            "evidence_id": "paper-a-chunk",
            "field": "retrieved_evidence",
            "quote": "paper-a Accuracy 90%",
            "page": 1,
        }
    ]
    normalized_event = next(
        event
        for event in events
        if event["type"] == "paper_reader_evidence_normalized"
    )
    assert normalized_event["data"] == {
        "assignment_id": "reader:paper-a",
        "role": "paper_reader",
        "normalized_evidence_count": 1,
        "raw_hit_fallback_used": True,
    }


@pytest.mark.asyncio
async def test_role_budget_applies_to_generated_tokens_not_prompt_tokens() -> None:
    registry = RoleProtocolRegistry.load(Path("backend/subagents/roles"))
    llm = ScriptedRoleLLM([], input_tokens=3200, output_tokens=200)
    runner = ProductionRoleRunner(
        registry,
        RoleExecutionContext(
            workspace_id="ws-1",
            conversation_id="conversation-1",
            task_id="task-1",
            question="比较论文中的方法与结果",
            blackboard=InMemoryBlackboardRepository(),
        ),
        llm_resolver=lambda _: llm,
        tool_runtime=RecordingSearchTool(),
    )

    result = await runner.invoke(
        RoleAssignment(
            assignment_id="reader:paper-a",
            role=AgentRole.PAPER_READER,
            paper_ids=["paper-a"],
            requested_tokens=1000,
            timeout_seconds=30,
        ),
        idempotency_key="task-1:reader:paper-a",
    )

    assert result.token_usage == 200


def _writer_payload(
    answer: str,
    citation_ids: list[str],
) -> dict[str, Any]:
    return {
        "answer": answer,
        "citation_ids": citation_ids,
        "issue_resolutions": [
            {
                "issue_id": "I1",
                "status": "accepted",
                "rationale": "已补充比较维度",
            }
        ],
    }


async def _prepared_writer(
    llm: ScriptedRoleLLM,
) -> tuple[ProductionRoleRunner, InMemoryBlackboardRepository, list[dict[str, object]]]:
    registry = RoleProtocolRegistry.load(Path("backend/subagents/roles"))
    board = InMemoryBlackboardRepository()
    events: list[dict[str, object]] = []
    runner = ProductionRoleRunner(
        registry,
        RoleExecutionContext(
            workspace_id="ws-1",
            conversation_id="conversation-1",
            task_id="task-writer",
            question="比较两篇论文",
            blackboard=board,
        ),
        llm_resolver=lambda _: llm,
        tool_runtime=RecordingSearchTool(),
        progress_sink=events.append,
    )
    for assignment in (
        _assignment(AgentRole.PAPER_READER, "reader:paper-a", ["paper-a"]),
        _assignment(AgentRole.PAPER_READER, "reader:paper-b", ["paper-b"]),
        _assignment(AgentRole.EVIDENCE, "evidence", ["paper-a", "paper-b"]),
        _assignment(AgentRole.CRITIC, "critic", ["paper-a", "paper-b"]),
    ):
        result = await runner.invoke(
            assignment,
            idempotency_key=f"task-writer:{assignment.assignment_id}",
        )
        for entry in result.blackboard_entries:
            await board.append(entry, expected_version=0)
    return runner, board, events


@pytest.mark.asyncio
async def test_writer_canonicalizes_valid_inline_citations_without_model_repair() -> None:
    llm = ScriptedRoleLLM(
        [],
        writer_payloads=[
            _writer_payload(
                "论文 A 与论文 B 的结果均为 90% [E1, E2]",
                ["E1"],
            )
        ],
    )
    runner, board, events = await _prepared_writer(llm)

    result = await runner.invoke(
        _assignment(AgentRole.WRITER, "writer", ["paper-a", "paper-b"]),
        idempotency_key="task-writer:writer",
    )
    for entry in result.blackboard_entries:
        await board.append(entry, expected_version=0)

    assert llm.writer_calls == 1
    assert result.output["citation_refs"] == [
        "artifact://citation/E1",
        "artifact://citation/E2",
    ]
    draft = next(
        entry
        for entry in await board.list_active("ws-1", "task-writer")
        if entry.kind is BlackboardEntryKind.DRAFT_SECTION
    )
    assert draft.payload["citation_ids"] == ["E1", "E2"]
    assert any(event["type"] == "writer_citations_normalized" for event in events)


@pytest.mark.asyncio
async def test_writer_runs_one_targeted_repair_before_degradation() -> None:
    llm = ScriptedRoleLLM(
        [],
        writer_payloads=[
            _writer_payload("不合法引用 [E99]", ["E99"]),
            _writer_payload("修复后的比较 [E1][E2]", ["E1", "E2"]),
        ],
    )
    runner, _, events = await _prepared_writer(llm)

    result = await runner.invoke(
        _assignment(AgentRole.WRITER, "writer", ["paper-a", "paper-b"]),
        idempotency_key="task-writer:writer",
    )

    assert llm.writer_calls == 2
    assert result.output["citation_refs"] == [
        "artifact://citation/E1",
        "artifact://citation/E2",
    ]
    assert any(event["type"] == "writer_agent_repair_started" for event in events)
    assert any(event["type"] == "writer_agent_repair_completed" for event in events)


@pytest.mark.asyncio
async def test_writer_strictly_degrades_only_from_complete_conflict_free_evidence() -> None:
    llm = ScriptedRoleLLM(
        [],
        writer_payloads=[_writer_payload("不合法引用 [E99]", ["E99"])],
    )
    runner, _, events = await _prepared_writer(llm)

    result = await runner.invoke(
        _assignment(AgentRole.WRITER, "writer", ["paper-a", "paper-b"]),
        idempotency_key="task-writer:writer",
    )

    assert llm.writer_calls == 2
    assert result.blackboard_entries[0].payload["degraded"] is True
    assert result.output["citation_refs"] == [
        "artifact://citation/E1",
        "artifact://citation/E2",
    ]
    assert any(event["type"] == "writer_agent_degraded" for event in events)


@pytest.mark.asyncio
async def test_writer_schema_invalid_repair_still_uses_strict_degradation() -> None:
    llm = ScriptedRoleLLM(
        [],
        writer_payloads=[
            _writer_payload("不合法引用 [E99]", ["E99"]),
            "not schema-valid writer json",
        ],
    )
    runner, _, events = await _prepared_writer(llm)

    result = await runner.invoke(
        _assignment(AgentRole.WRITER, "writer", ["paper-a", "paper-b"]),
        idempotency_key="task-writer:writer",
    )

    assert llm.writer_calls == 2
    assert result.blackboard_entries[0].payload["degraded"] is True
    assert any(event["type"] == "writer_agent_repair_failed" for event in events)
    assert any(event["type"] == "writer_agent_degraded" for event in events)


@pytest.mark.asyncio
async def test_writer_schema_invalid_revision_retains_strict_evidence_draft() -> None:
    llm = ScriptedRoleLLM(
        [],
        writer_payloads=[
            _writer_payload("不合法引用 [E99]", ["E99"]),
            "not schema-valid repair json",
        ],
    )
    runner, board, events = await _prepared_writer(llm)

    initial = await runner.invoke(
        _assignment(AgentRole.WRITER, "writer", ["paper-a", "paper-b"]),
        idempotency_key="task-writer:writer",
    )
    for entry in initial.blackboard_entries:
        await board.append(entry, expected_version=0)
    verification = await runner.invoke(
        _assignment(AgentRole.VERIFIER, "verifier", ["paper-a", "paper-b"]),
        idempotency_key="task-writer:verifier",
    )
    for entry in verification.blackboard_entries:
        await board.append(entry, expected_version=0)

    revision = await runner.invoke(
        _assignment(
            AgentRole.WRITER,
            "writer:revision",
            ["paper-a", "paper-b"],
        ),
        idempotency_key="task-writer:writer:revision",
    )

    payload = revision.blackboard_entries[0].payload
    assert payload["degraded"] is True
    assert payload["degradation_reason"] == (
        "writer_revision_generation_failed_evidence_only_fallback"
    )
    assert "| 论文 A |" in payload["answer"]
    assert "| 论文 B |" in payload["answer"]
    assert "只并列展示两篇论文各自的原文证据" in payload["answer"]
    assert "paper-a Accuracy 90%" in payload["answer"]
    assert "paper-b Accuracy 90%" in payload["answer"]
    assert "论文 1" not in payload["answer"]
    assert any(
        event["type"] == "writer_agent_degraded"
        and event["data"]["assignment_id"] == "writer:revision"
        for event in events
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "verifier_payload",
    [
        {
            "status": "failed",
            "findings": [
                {
                    "finding_type": "unsupported",
                    "description": "Side-by-side facts are not a direct comparison",
                    "severity": "severe",
                }
            ],
        },
        "not schema-valid verifier json",
    ],
)
async def test_canonical_evidence_only_draft_has_strict_deterministic_verifier_fallback(
    verifier_payload: dict[str, Any] | str,
) -> None:
    llm = ScriptedRoleLLM(
        [],
        writer_payloads=[
            _writer_payload("不合法引用 [E99]", ["E99"]),
            "not schema-valid repair json",
        ],
        verifier_payload=verifier_payload,
    )
    runner, board, events = await _prepared_writer(llm)
    writer = await runner.invoke(
        _assignment(AgentRole.WRITER, "writer", ["paper-a", "paper-b"]),
        idempotency_key="task-writer:writer",
    )
    for entry in writer.blackboard_entries:
        await board.append(entry, expected_version=0)

    verification = await runner.invoke(
        _assignment(AgentRole.VERIFIER, "verifier", ["paper-a", "paper-b"]),
        idempotency_key="task-writer:verifier",
    )

    assert verification.output["status"] == "passed"
    payload = verification.blackboard_entries[0].payload
    assert payload["deterministic_evidence_only_pass"] is True
    assert any(
        event["type"] == "verifier_deterministic_degraded_pass"
        for event in events
    )


@pytest.mark.asyncio
async def test_writer_refuses_degradation_when_evidence_has_conflicts() -> None:
    llm = ScriptedRoleLLM(
        [],
        writer_payloads=[_writer_payload("不合法引用 [E99]", ["E99"])],
        evidence_conflict_ids=["conflict-1"],
    )
    runner, _, events = await _prepared_writer(llm)

    with pytest.raises(Exception, match="strict degradation requirements"):
        await runner.invoke(
            _assignment(AgentRole.WRITER, "writer", ["paper-a", "paper-b"]),
            idempotency_key="task-writer:writer",
        )

    assert llm.writer_calls == 2
    assert not any(event["type"] == "writer_agent_degraded" for event in events)
