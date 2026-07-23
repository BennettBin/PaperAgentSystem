"""Production local worker that consumes PaperAgent Redis queues."""

from __future__ import annotations

import asyncio
import os
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from minio import Minio
from redis import Redis

from backend.agent_runtime.skill_selector import SkillSelector
from backend.agent_runtime.unified import (
    RuntimeCapabilities,
    UnifiedAgentRuntime,
    UnifiedRuntimeRouter,
)
from backend.apps.api.product_service import (
    LOCAL_WORKSPACE_ID,
    PaperAgentProcessor,
)
from backend.infrastructure.config import InfrastructureSettings
from backend.infrastructure.minio.object_store import MinioObjectStore
from backend.infrastructure.postgres.database import Database
from backend.infrastructure.postgres.schema import ensure_database_schema
from backend.infrastructure.redis.queue import RedisTaskQueue
from backend.infrastructure.sse.service import TaskEventStore
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
from backend.skills.loader import SkillManifestLoader, SkillRegistry
from backend.skills.runtime import SkillRuntime


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

    unified_runtime = UnifiedAgentRuntime(
        UnifiedRuntimeRouter(
            RuntimeCapabilities(
                dynamic_planner_enabled=_env_flag("DYNAMIC_PLANNER_ENABLED"),
                multi_agent_enabled=_env_flag("MULTI_AGENT_ENABLED"),
                allow_experimental_no_go=_env_flag("ALLOW_EXPERIMENTAL_NO_GO"),
                cascade_enabled=False,
            )
        ),
        progress_sink=publish_runtime_progress,
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
    processor = PaperAgentProcessor(
        database.session_factory,
        object_store,
        MultilingualHashEmbeddingClient(),
        MultilingualLexicalReranker(),
        llm,
        events,
        decision_llm=decision_llm,
        trace_writer=trace_writer,
        audit_log_writer=audit_logs,
        unified_runtime=unified_runtime,
        skill_runtime=skill_runtime,
    )
    queue.register_handler(
        "document_parse", lambda payload: asyncio.run(processor.parse(payload))
    )
    queue.register_handler(
        "main_agent", lambda payload: asyncio.run(processor.answer(payload))
    )
    threading.Thread(target=_serve_health, daemon=True).start()
    queue.recover_stale()
    while True:
        consumed = False
        for queue_name in ("document_parse", "main_agent", "sub_agent", "memory_summary"):
            consumed = queue.execute_next(queue_name, timeout=1) is not None or consumed
        if not consumed:
            time.sleep(0.1)


def _env_flag(name: str) -> bool:
    return os.getenv(name, "false").strip().casefold() in {"1", "true", "yes", "on"}


def _runtime_event_title(event_type: str) -> str:
    return {
        "runtime_routed": "已选择 Agent 执行路径",
        "model_selected": "已选择模型 Profile",
        "runtime_fallback": "高级路径不可用，回退安全流程",
        "plan_created": "已生成公开执行计划",
        "subagent_started": "多 Agent 协作已开始",
        "step_completed": "执行步骤已完成",
        "verification_completed": "结果核验完成",
    }.get(event_type, "Agent 进度更新")


if __name__ == "__main__":
    main()
