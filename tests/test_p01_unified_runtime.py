from __future__ import annotations

import pytest

from backend.agent_runtime.unified import (
    AdvancedRuntimeResult,
    PublicExecutionPlan,
    PublicPlanStep,
    RuntimeCapabilities,
    RuntimeMode,
    RuntimeRequest,
    UnifiedAgentRuntime,
    UnifiedRuntimeRouter,
    migrate_legacy_task_metadata,
)


class RecordingAdvancedRuntime:
    def __init__(self) -> None:
        self.requests: list[RuntimeRequest] = []

    async def execute(self, request: RuntimeRequest) -> AdvancedRuntimeResult:
        self.requests.append(request)
        return AdvancedRuntimeResult(
            answer="bounded result [E1]",
            citation_ids=["E1"],
            public_steps=["plan", "retrieve", "verify"],
        )


class RecordingPlanner:
    def __init__(self) -> None:
        self.requests: list[RuntimeRequest] = []

    async def create_plan(self, request: RuntimeRequest) -> PublicExecutionPlan:
        self.requests.append(request)
        return PublicExecutionPlan(
            plan_id=f"plan-{request.task_id}",
            version=1,
            goal=request.question,
            termination_condition="verified answer",
            steps=[
                PublicPlanStep(
                    step_id="retrieve",
                    title="检索论文证据",
                    step_type="tool_call",
                ),
                PublicPlanStep(
                    step_id="answer",
                    title="生成并核验回答",
                    step_type="generate",
                    depends_on=["retrieve"],
                ),
            ],
        )


@pytest.mark.parametrize(
    ("multi_enabled", "experimental_enabled"),
    [
        (False, False),
        (True, False),
        (False, True),
    ],
)
def test_multi_agent_requires_both_feature_gates(
    multi_enabled: bool,
    experimental_enabled: bool,
) -> None:
    router = UnifiedRuntimeRouter(
        RuntimeCapabilities(
            multi_agent_enabled=multi_enabled,
            allow_experimental_no_go=experimental_enabled,
        )
    )

    decision = router.route(
        RuntimeRequest(
            task_id="gated",
            question="综合比较两篇论文",
            file_ids=["f1", "f2"],
        )
    )

    assert decision.mode is RuntimeMode.DYNAMIC_PLAN
    assert decision.fallback_reason == "multi_agent_not_promoted"


@pytest.mark.parametrize(
    ("question", "file_ids"),
    [
        ("比较这篇论文的方法", ["f1"]),
        ("综合这些研究的结论", ["f1"]),
        ("回答两篇论文分别发表于哪一年", ["f1", "f2"]),
    ],
)
def test_multi_agent_requires_multiple_files_and_explicit_collaboration_intent(
    question: str,
    file_ids: list[str],
) -> None:
    router = UnifiedRuntimeRouter(
        RuntimeCapabilities(
            multi_agent_enabled=True,
            allow_experimental_no_go=True,
        )
    )

    decision = router.route(
        RuntimeRequest(task_id="eligibility", question=question, file_ids=file_ids)
    )

    assert decision.mode is RuntimeMode.DYNAMIC_PLAN
    assert decision.fallback_reason is None


def test_multi_agent_route_accepts_deduplicated_multi_file_synthesis() -> None:
    router = UnifiedRuntimeRouter(
        RuntimeCapabilities(
            multi_agent_enabled=True,
            allow_experimental_no_go=True,
        )
    )

    decision = router.route(
        RuntimeRequest(
            task_id="eligible",
            question="综合分析三篇论文",
            file_ids=["f1", "f1", "f2", "f3"],
        )
    )

    assert decision.mode is RuntimeMode.MULTI_AGENT
    assert decision.fallback_reason is None


def test_router_uses_dynamic_planner_for_default_paper_path() -> None:
    router = UnifiedRuntimeRouter(RuntimeCapabilities())
    simple = router.route(RuntimeRequest(task_id="t1", question="你好", file_ids=[]))
    assert simple.mode is RuntimeMode.FAST_PATH
    assert simple.model_route == "large_base"
    assert simple.cascade_status == "unavailable_o_skipped"

    complex_request = RuntimeRequest(
        task_id="t2",
        question="比较三篇论文并形成有引用的综述",
        file_ids=["f1", "f2", "f3"],
    )
    planned = router.route(complex_request)
    assert planned.mode is RuntimeMode.DYNAMIC_PLAN
    assert planned.fallback_reason == "multi_agent_not_promoted"


@pytest.mark.asyncio
async def test_dynamic_and_multi_agent_paths_are_injectable_bounded_and_public_only() -> None:
    advanced = RecordingAdvancedRuntime()
    planner = RecordingPlanner()
    progress: list[dict[str, object]] = []
    runtime = UnifiedAgentRuntime(
        UnifiedRuntimeRouter(
            RuntimeCapabilities(
                dynamic_planner_enabled=True,
                multi_agent_enabled=True,
                allow_experimental_no_go=True,
            )
        ),
        advanced_runtime=advanced,
        dynamic_planner=planner,
        progress_sink=progress.append,
    )
    dynamic = await runtime.execute(
        RuntimeRequest(
            task_id="dynamic",
            question="检索失败后换查询策略并重新规划",
            file_ids=["f1"],
        )
    )
    multi = await runtime.execute(
        RuntimeRequest(
            task_id="multi",
            question="比较三篇论文并写综述",
            file_ids=["f1", "f2", "f3"],
        )
    )
    assert dynamic.decision.mode is RuntimeMode.DYNAMIC_PLAN
    assert multi.decision.mode is RuntimeMode.MULTI_AGENT
    assert dynamic.public_plan is not None
    assert multi.advanced_result is not None
    assert len(advanced.requests) == 1
    assert [request.task_id for request in planner.requests] == ["dynamic"]
    assert {event["type"] for event in progress} >= {
        "plan_created",
        "subagent_started",
        "verification_completed",
    }
    serialized = str(progress).casefold()
    assert "hidden_reasoning" not in serialized
    assert "chain_of_thought" not in serialized


@pytest.mark.asyncio
async def test_missing_advanced_runtime_falls_back_to_safe_rag() -> None:
    runtime = UnifiedAgentRuntime(
        UnifiedRuntimeRouter(
            RuntimeCapabilities(
                multi_agent_enabled=True,
                allow_experimental_no_go=True,
            )
        )
    )

    execution = await runtime.execute(
        RuntimeRequest(
            task_id="missing-adapter",
            question="比较两篇论文",
            file_ids=["f1", "f2"],
        )
    )

    assert execution.decision.mode is RuntimeMode.SAFE_RAG
    assert execution.decision.fallback_reason == "advanced_runtime_unavailable"
    assert execution.advanced_result is None


@pytest.mark.asyncio
async def test_missing_dynamic_planner_falls_back_to_safe_rag() -> None:
    runtime = UnifiedAgentRuntime(UnifiedRuntimeRouter(RuntimeCapabilities()))

    execution = await runtime.execute(
        RuntimeRequest(
            task_id="missing-planner",
            question="总结这篇论文",
            file_ids=["f1"],
        )
    )

    assert execution.decision.mode is RuntimeMode.SAFE_RAG
    assert execution.decision.fallback_reason == "dynamic_planner_unavailable"
    assert execution.public_plan is None


def test_legacy_task_metadata_migration_is_idempotent_and_fail_safe() -> None:
    migrated = migrate_legacy_task_metadata({"legacy": True})
    assert migrated["runtime_schema_version"] == "2.0"
    assert migrated["runtime_mode"] == "legacy_safe"
    assert migrated["plan_schema_version"] == "1.0"
    assert migrate_legacy_task_metadata(migrated) == migrated
