from __future__ import annotations

import pytest

from backend.agent_runtime.unified import (
    AdvancedRuntimeResult,
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


def test_router_keeps_no_go_features_off_default_path_and_cascade_unavailable() -> None:
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
    fallback = router.route(complex_request)
    assert fallback.mode is RuntimeMode.SAFE_RAG
    assert fallback.fallback_reason == "multi_agent_not_promoted"


@pytest.mark.asyncio
async def test_dynamic_and_multi_agent_paths_are_injectable_bounded_and_public_only() -> None:
    advanced = RecordingAdvancedRuntime()
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
    assert dynamic.advanced_result is not None
    assert multi.advanced_result is not None
    assert len(advanced.requests) == 2
    assert {event["type"] for event in progress} >= {
        "plan_created",
        "subagent_started",
        "verification_completed",
    }
    serialized = str(progress).casefold()
    assert "hidden_reasoning" not in serialized
    assert "chain_of_thought" not in serialized


def test_legacy_task_metadata_migration_is_idempotent_and_fail_safe() -> None:
    migrated = migrate_legacy_task_metadata({"legacy": True})
    assert migrated["runtime_schema_version"] == "2.0"
    assert migrated["runtime_mode"] == "legacy_safe"
    assert migrated["plan_schema_version"] == "1.0"
    assert migrate_legacy_task_metadata(migrated) == migrated
