"""Production local worker that consumes PaperAgent Redis queues."""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from collections.abc import Callable
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from minio import Minio
from redis import Redis

from backend.agent_runtime.llm_planner import (
    ConstrainedLLMPlanner,
    PlannerModelMetadata,
)
from backend.agent_runtime.planner import RegistrySnapshot
from backend.agent_runtime.planner_runtime_adapter import (
    DynamicPlannerRuntimeAdapter,
)
from backend.agent_runtime.skill_selector import SkillSelector
from backend.agent_runtime.unified import (
    AdvancedRuntimePort,
    DynamicPlannerPort,
    RuntimeCapabilities,
    UnifiedAgentRuntime,
    UnifiedRuntimeRouter,
)
from backend.apps.api.product_service import (
    LOCAL_WORKSPACE_ID,
    PaperAgentProcessor,
)
from backend.core.errors import ErrorCode, ProjectError
from backend.infrastructure.config import InfrastructureSettings
from backend.infrastructure.minio.object_store import MinioObjectStore
from backend.infrastructure.postgres.blackboard import (
    ManagedSqlAlchemyBlackboardRepository,
)
from backend.infrastructure.postgres.database import Database
from backend.infrastructure.postgres.schema import ensure_database_schema
from backend.infrastructure.redis.queue import RedisTaskQueue
from backend.infrastructure.sse.service import TaskEventStore
from backend.memory import (
    ConversationMemoryCoordinator,
    LongTermMemoryService,
    ShortTermMemoryService,
)
from backend.models.runtime import (
    ModelRuntimeService,
    OllamaRuntime,
    RuntimeSelectedLLMClient,
)
from backend.observability.task_audit_log import JsonlTaskAuditLogWriter
from backend.observability.tracing import SqlAlchemyTraceWriter
from backend.rag.local_models import (
    MultilingualHashEmbeddingClient,
    MultilingualLexicalReranker,
)
from backend.rag.retrieval import HybridRetriever
from backend.skills.loader import SkillManifestLoader, SkillRegistry
from backend.skills.runtime import SkillRuntime
from backend.subagents.protocol import RoleProtocolRegistry
from backend.subagents.role_runner import (
    ProductionRoleRunner,
    RoleExecutionContext,
)
from backend.subagents.runtime_adapter import MultiAgentRuntimeAdapter
from backend.tool_runtime.document_tools import SearchDocumentTool
from backend.tool_runtime.runtime import (
    InMemoryDataRefStore,
    InMemoryIdempotencyStore,
    ToolRegistry,
    ToolRuntime,
)

LOGGER = logging.getLogger(__name__)


def register_worker_handlers(
    queue: RedisTaskQueue,
    processor: PaperAgentProcessor,
    memory_coordinator: ConversationMemoryCoordinator,
) -> None:
    """Register every production task handled by the default Worker."""
    queue.register_handler(
        "document_parse", lambda payload: asyncio.run(processor.parse(payload))
    )
    queue.register_handler(
        "main_agent", lambda payload: asyncio.run(processor.answer(payload))
    )
    queue.register_handler(
        "memory_summary",
        lambda payload: asyncio.run(
            memory_coordinator.summarize(
                str(payload["workspace_id"]),
                str(payload["conversation_id"]),
            )
        ),
    )


class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path not in {"/health", "/health/live", "/health/ready"}:
            self.send_response(HTTPStatus.NOT_FOUND)
            self.end_headers()
            return
        body = b'{"status":"ready","service":"worker"}'
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *args: object) -> None:
        return


def _serve_health() -> None:
    ThreadingHTTPServer(("0.0.0.0", 8090), _HealthHandler).serve_forever()


def build_unified_runtime(
    multi_agent_runtime: AdvancedRuntimePort,
    dynamic_planner: DynamicPlannerPort,
    progress_sink: Callable[[dict[str, object]], None],
) -> UnifiedAgentRuntime:
    """Build the default Planner path and separately gated multi-Agent path."""
    capabilities = RuntimeCapabilities(
        dynamic_planner_enabled=_env_flag("DYNAMIC_PLANNER_ENABLED", default=True),
        multi_agent_enabled=_env_flag("MULTI_AGENT_ENABLED"),
        allow_experimental_no_go=_env_flag("ALLOW_EXPERIMENTAL_NO_GO"),
        cascade_enabled=False,
    )
    LOGGER.info(
        "Agent feature gates: multi_agent_enabled=%s "
        "allow_experimental_no_go=%s dynamic_planner_enabled=%s",
        capabilities.multi_agent_enabled,
        capabilities.allow_experimental_no_go,
        capabilities.dynamic_planner_enabled,
    )
    return UnifiedAgentRuntime(
        UnifiedRuntimeRouter(capabilities),
        multi_agent_runtime=multi_agent_runtime,
        dynamic_planner=dynamic_planner,
        progress_sink=progress_sink,
    )


def main() -> None:
    settings = InfrastructureSettings()
    database = Database(settings.database_url)
    ensure_database_schema(database.engine)
    redis = Redis.from_url(settings.redis_url)
    queue = RedisTaskQueue(redis, database.session_factory)
    object_store = MinioObjectStore(
        Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
        ),
        database.session_factory,
        LOCAL_WORKSPACE_ID,
        settings.minio_bucket_prefix,
    )
    model_runtime = ModelRuntimeService(
        database.session_factory,
        OllamaRuntime(
            os.getenv("OLLAMA_ENDPOINT", "http://host.docker.internal:11434")
        ),
    )
    llm = RuntimeSelectedLLMClient(model_runtime, "large")
    decision_llm = RuntimeSelectedLLMClient(model_runtime, "small")
    events = TaskEventStore(database.session_factory, redis)
    audit_logs = JsonlTaskAuditLogWriter(os.getenv("AGENT_LOG_DIR", "runtime/logs/agent"))

    def publish_runtime_progress(event: dict[str, object]) -> None:
        task_id = str(event["task_id"])
        event_type = str(event["type"])
        event_data = event.get("data")
        events.append(
            task_id,
            event_type,
            _runtime_event_title(event_type),
            event_data if isinstance(event_data, dict) else {},
        )
        audit_logs.append(
            task_id,
            event_type,
            component="unified_agent_runtime",
            status="recorded",
            details={
                "event_type": event_type,
                "title": _runtime_event_title(event_type),
                **(event_data if isinstance(event_data, dict) else {}),
            },
        )

    trace_writer = SqlAlchemyTraceWriter(database.session_factory)
    skill_registry = SkillRegistry(trace_writer)
    skill_registry.load_all(
        SkillManifestLoader(
            Path(__file__).resolve().parents[2] / "skills",
            registered_tools={
                "parse_document", "get_document_section", "search_document",
                "build_comparison_table", "save_artifact",
                "build_literature_review", "extract_paper_card",
            },
            available_profiles={"development", "paper_reader_v1"},
        )
    )
    skill_runtime = SkillRuntime(
        SkillSelector(skill_registry, fallback_skill="paper_reader"),
        skill_registry,
    )
    embeddings = MultilingualHashEmbeddingClient()
    reranker = MultilingualLexicalReranker()
    retriever = HybridRetriever(database.session_factory, embeddings, reranker)
    role_registry = RoleProtocolRegistry.load(
        Path(__file__).resolve().parents[2] / "subagents" / "roles"
    )
    role_profiles = {
        manifest.model_profile for manifest in role_registry.manifests.values()
    }

    def resolve_role_model(profile: str) -> RuntimeSelectedLLMClient:
        if profile not in role_profiles:
            raise ProjectError(
                ErrorCode.UNAVAILABLE,
                "Sub Agent model profile is not registered",
                {"model_profile": profile},
            )
        return llm

    tool_registry = ToolRegistry()
    tool_registry.register(SearchDocumentTool(retriever))
    tool_runtime = ToolRuntime(
        tool_registry,
        idempotency_store=InMemoryIdempotencyStore(),
        data_ref_store=InMemoryDataRefStore(),
        trace_writer=trace_writer,
        max_inline_bytes=512 * 1024,
    )

    def build_role_runner(
        context: RoleExecutionContext,
    ) -> ProductionRoleRunner:
        return ProductionRoleRunner(
            role_registry,
            context,
            llm_resolver=resolve_role_model,
            tool_runtime=tool_runtime,
            trace_writer=trace_writer,
            progress_sink=publish_runtime_progress,
            cancellation_check=lambda: queue.is_cancelled(context.task_id),
        )

    multi_agent_runtime = MultiAgentRuntimeAdapter(
        registry=role_registry,
        runner_factory=build_role_runner,
        blackboard_factory=lambda: ManagedSqlAlchemyBlackboardRepository(
            database.session_factory
        ),
        progress_sink=publish_runtime_progress,
        cancellation_check=queue.is_cancelled,
        trace_writer=trace_writer,
    )
    planner_skill_names = sorted(skill.name for skill in skill_registry.list_all())
    planner_tool_schemas: dict[str, dict[str, object]] = {
        "search_document": SearchDocumentTool.input_model.model_json_schema(),
    }
    planner_registry = RegistrySnapshot(
        skills=set(planner_skill_names),
        tools=set(planner_tool_schemas),
        permitted_skills=set(planner_skill_names),
        permitted_tools=set(planner_tool_schemas),
    )
    dynamic_planner = DynamicPlannerRuntimeAdapter(
        ConstrainedLLMPlanner(
            llm=decision_llm,
            registry=planner_registry,
            model=PlannerModelMetadata(
                model="runtime-selected-small",
                profile="small",
                version="selected",
                prompt_version="planner-v2",
            ),
        ),
        skill_names=planner_skill_names,
        tool_schemas=planner_tool_schemas,
    )
    unified_runtime = build_unified_runtime(
        multi_agent_runtime,
        dynamic_planner,
        publish_runtime_progress,
    )
    short_term_memory = ShortTermMemoryService(
        database.session_factory,
        embeddings,
    )
    long_term_memory = LongTermMemoryService(
        database.session_factory,
        embeddings,
    )
    memory_coordinator = ConversationMemoryCoordinator(
        short_term_memory,
        long_term_memory,
    )
    processor = PaperAgentProcessor(
        database.session_factory,
        object_store,
        embeddings,
        reranker,
        llm,
        events,
        decision_llm=decision_llm,
        trace_writer=trace_writer,
        audit_log_writer=audit_logs,
        unified_runtime=unified_runtime,
        skill_runtime=skill_runtime,
        short_term_memory=short_term_memory,
        long_term_memory=long_term_memory,
        memory_task_queue=queue,
    )
    register_worker_handlers(
        queue,
        processor,
        memory_coordinator,
    )
    threading.Thread(target=_serve_health, daemon=True).start()
    queue.recover_stale()
    while True:
        consumed = False
        for queue_name in ("document_parse", "main_agent", "memory_summary"):
            consumed = queue.execute_next(queue_name, timeout=1) is not None or consumed
        if not consumed:
            time.sleep(0.1)


def _env_flag(name: str, *, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().casefold() in {"1", "true", "yes", "on"}


def _runtime_event_title(event_type: str) -> str:
    return {
        "runtime_routed": "已选择 Agent 执行路径",
        "model_selected": "已选择模型 Profile",
        "runtime_fallback": "高级路径不可用，回退安全流程",
        "plan_created": "已生成公开执行计划",
        "plan_step_started": "动态计划步骤已开始",
        "plan_step_completed": "动态计划步骤已完成",
        "plan_step_skipped": "动态计划步骤未执行",
        "plan_revised": "动态执行计划已更新",
        "plan_completed": "动态执行计划已结束",
        "subagent_started": "多 Agent 协作已开始",
        "step_completed": "执行步骤已完成",
        "verification_completed": "结果核验完成",
        "multi_agent_started": "多 Agent 生产链已启动",
        "multi_agent_completed": "多 Agent 生产链已完成",
        "multi_agent_degraded": "多 Agent 生产链已降级完成",
        "multi_agent_failed": "多 Agent 生产链执行失败",
        "multi_agent_revision_started": "Writer 开始定向修订",
        "multi_agent_revision_completed": "Verifier 已通过修订结果",
        "multi_agent_idempotency_replayed": "已复用通过核验的历史执行结果",
        "coordinator_agent_started": "Coordinator Agent 开始任务编排",
        "coordinator_agent_completed": "Coordinator Agent 已完成任务编排",
        "coordinator_agent_failed": "Coordinator Agent 编排失败",
        "paper_reader_agent_started": "Paper Reader 开始读取指定论文",
        "paper_reader_agent_completed": "Paper Reader 已生成论文卡片",
        "paper_reader_agent_failed": "Paper Reader 执行失败",
        "evidence_agent_started": "Evidence Agent 开始构建证据矩阵",
        "evidence_agent_completed": "Evidence Agent 已完成证据矩阵",
        "evidence_agent_failed": "Evidence Agent 执行失败",
        "critic_agent_started": "Critic Agent 开始审阅证据",
        "critic_agent_completed": "Critic Agent 已完成问题清单",
        "critic_agent_failed": "Critic Agent 不可用，进入降级路径",
        "writer_agent_started": "Writer Agent 开始生成回答",
        "writer_agent_completed": "Writer Agent 已生成引用草稿",
        "writer_agent_failed": "Writer Agent 执行失败",
        "verifier_agent_started": "Verifier Agent 开始独立核验",
        "verifier_agent_completed": "Verifier Agent 已完成核验",
        "verifier_agent_passed": "Verifier Agent 核验通过",
        "verifier_agent_failed": "Verifier Agent 核验失败",
    }.get(event_type, "Agent 进度更新")


if __name__ == "__main__":
    main()
