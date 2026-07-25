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
    def __init__(self, requested_profiles: list[str]) -> None:
        self.requested_profiles = requested_profiles
        self.last_usage = SimpleNamespace(total_tokens=20)

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
                    "evidence": [
                        {
                            "evidence_id": f"{file_id}-chunk",
                            "field": "methodology",
                            "quote": f"{file_id} Accuracy 90%",
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
                    "conflict_ids": [],
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
                            "severity": "warning",
                        }
                    ]
                }
            )
        if prompt.startswith("ROLE: writer"):
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
