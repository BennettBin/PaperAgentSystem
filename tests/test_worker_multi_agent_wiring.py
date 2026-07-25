from __future__ import annotations

import pytest

from backend.agent_runtime.unified import (
    AdvancedRuntimeResult,
    PublicExecutionPlan,
    PublicPlanStep,
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


class RecordingPlanner:
    async def create_plan(self, request: RuntimeRequest) -> PublicExecutionPlan:
        return PublicExecutionPlan(
            plan_id=f"plan-{request.task_id}",
            version=1,
            goal=request.question,
            termination_condition="done",
            steps=[
                PublicPlanStep(
                    step_id="answer",
                    title="生成回答",
                    step_type="generate",
                )
            ],
        )


@pytest.mark.asyncio
async def test_worker_runtime_injects_adapter_but_keeps_dual_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = RecordingMultiAgentRuntime()
    planner = RecordingPlanner()
    monkeypatch.setenv("MULTI_AGENT_ENABLED", "false")
    monkeypatch.setenv("ALLOW_EXPERIMENTAL_NO_GO", "true")
    runtime = build_unified_runtime(adapter, planner, lambda _: None)

    disabled = await runtime.execute(
        RuntimeRequest(
            task_id="disabled",
            question="比较两篇论文",
            file_ids=["paper-a", "paper-b"],
        )
    )

    assert runtime._multi_agent is adapter  # noqa: SLF001
    assert disabled.decision.mode is RuntimeMode.DYNAMIC_PLAN
    assert disabled.public_plan is not None
    assert adapter.calls == []

    monkeypatch.setenv("MULTI_AGENT_ENABLED", "true")
    enabled_runtime = build_unified_runtime(
        adapter,
        planner,
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
