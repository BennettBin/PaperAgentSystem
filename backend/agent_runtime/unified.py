"""Feature-gated product routing for the unified Agent Runtime.

This layer exposes M/N capabilities through a Port without making either No-Go
path the production default. Stage O dependent cascade behavior fails closed.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RuntimeMode(StrEnum):
    FAST_PATH = "fast_path"
    SAFE_RAG = "safe_rag"
    DYNAMIC_PLAN = "dynamic_plan"
    MULTI_AGENT = "multi_agent"


class RuntimeCapabilities(_StrictModel):
    dynamic_planner_enabled: bool = False
    multi_agent_enabled: bool = False
    allow_experimental_no_go: bool = False
    cascade_enabled: bool = False


class RuntimeRequest(_StrictModel):
    task_id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    file_ids: list[str] = Field(default_factory=list)
    workspace_id: str = "local-workspace"
    conversation_id: str | None = None


class RuntimeDecision(_StrictModel):
    mode: RuntimeMode
    reason: str
    fallback_reason: str | None = None
    model_route: str
    model_transition: str
    cascade_status: str


class AdvancedEvidence(_StrictModel):
    id: str = Field(min_length=1)
    file_id: str = Field(min_length=1)
    page: int = Field(ge=1)
    section: list[str] = Field(default_factory=list)
    quote: str = Field(min_length=1)
    bbox: list[float] = Field(default_factory=list)
    source_evidence_id: str = Field(min_length=1)


class AdvancedRuntimeResult(_StrictModel):
    answer: str = Field(min_length=1)
    citation_ids: list[str] = Field(default_factory=list)
    evidence: list[AdvancedEvidence] = Field(default_factory=list)
    public_steps: list[str] = Field(default_factory=list)
    agent_roles: list[str] = Field(default_factory=list)
    subagent_run_ids: list[str] = Field(default_factory=list)
    blackboard_entry_ids: list[str] = Field(default_factory=list)
    degraded: bool = False
    revision_rounds: int = Field(default=0, ge=0, le=1)
    missing_file_ids: list[str] = Field(default_factory=list)


class UnifiedRuntimeExecution(_StrictModel):
    decision: RuntimeDecision
    advanced_result: AdvancedRuntimeResult | None = None


class AdvancedRuntimePort(Protocol):
    async def execute(self, request: RuntimeRequest) -> AdvancedRuntimeResult: ...


ProgressSink = Callable[[dict[str, object]], None]


class UnifiedRuntimeRouter:
    def __init__(self, capabilities: RuntimeCapabilities) -> None:
        self.capabilities = capabilities

    def route(self, request: RuntimeRequest) -> RuntimeDecision:
        normalized = request.question.casefold()
        wants_multi_intent = any(
            marker in normalized
            for marker in (
                "比较",
                "对比",
                "综述",
                "综合",
                "review",
                "compare",
                "synthesize",
            )
        )
        wants_multi = len(set(request.file_ids)) >= 2 and wants_multi_intent
        wants_dynamic = any(
            marker in normalized
            for marker in ("重新规划", "换查询", "检索失败", "replan", "retry strategy")
        )
        mode = RuntimeMode.FAST_PATH if not request.file_ids else RuntimeMode.SAFE_RAG
        reason = "simple request uses bounded fast path" if not request.file_ids else "safe RAG"
        fallback_reason: str | None = None
        if wants_multi:
            if self.capabilities.multi_agent_enabled and self.capabilities.allow_experimental_no_go:
                mode = RuntimeMode.MULTI_AGENT
                reason = "explicit experimental multi-paper route"
            else:
                mode = RuntimeMode.SAFE_RAG
                reason = "multi-paper request uses promoted safe path"
                fallback_reason = "multi_agent_not_promoted"
        elif wants_multi_intent:
            mode = RuntimeMode.SAFE_RAG
            reason = "multi-Agent intent requires at least two distinct papers"
            fallback_reason = "multi_agent_ineligible"
        elif wants_dynamic:
            if self.capabilities.dynamic_planner_enabled and self.capabilities.allow_experimental_no_go:
                mode = RuntimeMode.DYNAMIC_PLAN
                reason = "explicit experimental dynamic planning route"
            else:
                mode = RuntimeMode.SAFE_RAG
                reason = "dynamic request uses promoted safe path"
                fallback_reason = "dynamic_planner_not_promoted"
        return RuntimeDecision(
            mode=mode,
            reason=reason,
            fallback_reason=fallback_reason,
            model_route="large_base",
            model_transition="small_base_decision_to_large_base_generation",
            cascade_status=(
                "configured" if self.capabilities.cascade_enabled else "unavailable_o_skipped"
            ),
        )


class UnifiedAgentRuntime:
    def __init__(
        self,
        router: UnifiedRuntimeRouter,
        *,
        advanced_runtime: AdvancedRuntimePort | None = None,
        multi_agent_runtime: AdvancedRuntimePort | None = None,
        progress_sink: ProgressSink | None = None,
    ) -> None:
        self._router = router
        self._advanced = advanced_runtime
        self._multi_agent = multi_agent_runtime
        self._progress = progress_sink or (lambda _: None)

    async def execute(self, request: RuntimeRequest) -> UnifiedRuntimeExecution:
        decision = self._router.route(request)
        self._emit(
            request,
            "runtime_routed",
            {
                "mode": decision.mode.value,
                "reason": decision.reason,
                "fallback_reason": decision.fallback_reason,
            },
        )
        self._emit(
            request,
            "model_selected",
            {
                "route": decision.model_route,
                "transition": decision.model_transition,
                "cascade_status": decision.cascade_status,
            },
        )
        if decision.mode not in {RuntimeMode.DYNAMIC_PLAN, RuntimeMode.MULTI_AGENT}:
            return UnifiedRuntimeExecution(decision=decision)
        selected_runtime = (
            self._multi_agent or self._advanced
            if decision.mode is RuntimeMode.MULTI_AGENT
            else self._advanced
        )
        if selected_runtime is None:
            fallback = decision.model_copy(
                update={
                    "mode": RuntimeMode.SAFE_RAG,
                    "reason": "advanced runtime Adapter unavailable; use safe RAG",
                    "fallback_reason": "advanced_runtime_unavailable",
                }
            )
            self._emit(
                request,
                "runtime_fallback",
                {"mode": fallback.mode.value, "reason": fallback.fallback_reason},
            )
            return UnifiedRuntimeExecution(decision=fallback)
        if decision.mode is RuntimeMode.DYNAMIC_PLAN:
            self._emit(
                request,
                "plan_created",
                {"goal": "execute bounded research task", "max_replans": 2},
            )
        else:
            self._emit(
                request,
                "subagent_started",
                {
                    "agents": ["paper_reader", "evidence", "critic", "writer", "verifier"],
                    "max_depth": 1,
                },
            )
        result = await selected_runtime.execute(request)
        for index, step in enumerate(result.public_steps, 1):
            self._emit(
                request,
                "step_completed",
                {"step_index": index, "step_title": step},
            )
        self._emit(
            request,
            "verification_completed",
            {
                "citation_count": len(result.citation_ids),
                "passed": bool(result.citation_ids),
            },
        )
        return UnifiedRuntimeExecution(decision=decision, advanced_result=result)

    def _emit(
        self, request: RuntimeRequest, event_type: str, data: dict[str, object]
    ) -> None:
        self._progress(
            {
                "task_id": request.task_id,
                "type": event_type,
                "data": data,
            }
        )


def migrate_legacy_task_metadata(metadata: dict[str, object]) -> dict[str, object]:
    if metadata.get("runtime_schema_version") == "2.0":
        return dict(metadata)
    return {
        **metadata,
        "runtime_schema_version": "2.0",
        "runtime_mode": "legacy_safe",
        "plan_schema_version": str(metadata.get("plan_schema_version", "1.0")),
        "migration_strategy": "read_legacy_or_rebuild_derived_state",
    }
