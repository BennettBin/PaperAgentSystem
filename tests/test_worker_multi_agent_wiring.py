from __future__ import annotations

import pytest

from backend.agent_runtime.unified import (
    AdvancedRuntimeResult,
    RuntimeMode,
    RuntimeRequest,
)
from backend.apps.worker.runtime import build_unified_runtime


class RecordingMultiAgentRuntime:
    def __init__(self) -> None:
        self.calls: list[RuntimeRequest] = []

    async def execute(self, request: RuntimeRequest) -> AdvancedRuntimeResult:
        self.calls.append(request)
        return AdvancedRuntimeResult(
            answer="受核验的多论文回答 [E1]",
            citation_ids=["E1"],
        )


@pytest.mark.asyncio
async def test_worker_runtime_injects_adapter_but_keeps_dual_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = RecordingMultiAgentRuntime()
    monkeypatch.setenv("MULTI_AGENT_ENABLED", "false")
    monkeypatch.setenv("ALLOW_EXPERIMENTAL_NO_GO", "true")
    runtime = build_unified_runtime(adapter, lambda _: None)

    disabled = await runtime.execute(
        RuntimeRequest(
            task_id="disabled",
            question="比较两篇论文",
            file_ids=["paper-a", "paper-b"],
        )
    )

    assert runtime._multi_agent is adapter  # noqa: SLF001
    assert disabled.decision.mode is RuntimeMode.SAFE_RAG
    assert adapter.calls == []

    monkeypatch.setenv("MULTI_AGENT_ENABLED", "true")
    enabled_runtime = build_unified_runtime(
        adapter,
        lambda _: None,
    )
    enabled = await enabled_runtime.execute(
        RuntimeRequest(
            task_id="enabled",
            question="比较两篇论文",
            file_ids=["paper-a", "paper-b"],
        )
    )

    assert enabled.decision.mode is RuntimeMode.MULTI_AGENT
    assert enabled.advanced_result is not None
    assert [request.task_id for request in adapter.calls] == ["enabled"]
