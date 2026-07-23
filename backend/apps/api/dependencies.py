from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, AsyncIterator, Awaitable, Callable, Protocol, cast
from uuid import uuid4

from backend.core.ports.observability import Clock, IdGenerator
from backend.core.ports.storage import ObjectStore, TaskQueue

if TYPE_CHECKING:
    from backend.apps.api.product_service import PaperAgentApplicationPort
    from backend.infrastructure.config import InfrastructureSettings
    from backend.models.runtime import ModelRuntimeService
    from evaluation.dashboard import OfflineEvaluationDashboard
    from evaluation.hitl import StagingRegistry


class TaskEventStreamPort(Protocol):
    def sse(self, task_id: str, last_sequence: int = 0) -> AsyncIterator[str]: ...


@dataclass(frozen=True)
class ApiContainer:
    request_id_generator: IdGenerator
    trace_id_generator: IdGenerator
    clock: Clock
    task_queue: TaskQueue
    event_stream: TaskEventStreamPort | None = None
    object_store: ObjectStore | None = None
    paper_agent: "PaperAgentApplicationPort | None" = None
    model_runtime: "ModelRuntimeService | None" = None
    hitl_registry: "StagingRegistry | None" = None
    evaluation_dashboard: "OfflineEvaluationDashboard | None" = None
    readiness_checks: tuple[Callable[[], bool | Awaitable[bool]], ...] = ()

    async def is_ready(self) -> bool:
        for check in self.readiness_checks:
            result = check()
            if hasattr(result, "__await__"):
                result = await result
            if not result:
                return False
        return True


@dataclass(frozen=True)
class StaticUUIDGenerator(IdGenerator):
    def generate_id(self, prefix: str = "") -> str:
        return f"{prefix}{uuid4().hex}"

    def generate_request_id(self) -> str:
        return f"req-{uuid4().hex}"

    def generate_trace_id(self) -> str:
        return f"trace-{uuid4().hex}"


@dataclass(frozen=True)
class SystemClock(Clock):
    def now(self) -> datetime:
        return datetime.now(UTC)

    def now_timestamp(self) -> int:
        return int(self.now().timestamp())


def build_fake_container(
    request_id_generator: IdGenerator | None = None,
    trace_id_generator: IdGenerator | None = None,
    clock: Clock | None = None,
    task_queue: TaskQueue | None = None,
) -> ApiContainer:
    from backend.apps.worker.fake_queue import FakeTaskQueue

    selected_queue = task_queue or FakeTaskQueue()
    return ApiContainer(
        request_id_generator=request_id_generator or StaticUUIDGenerator(),
        trace_id_generator=trace_id_generator or StaticUUIDGenerator(),
        clock=clock or SystemClock(),
        task_queue=selected_queue,
        event_stream=None,
        object_store=None,
        readiness_checks=(lambda: True,),
    )


def build_infrastructure_container(
    settings: "InfrastructureSettings", workspace_id: str
) -> ApiContainer:
    import os
    from pathlib import Path

    from minio import Minio
    from redis import Redis
    from sqlalchemy import text

    from backend.apps.api.product_service import LOCAL_USER_ID, PaperAgentApplication
    from backend.infrastructure.minio.object_store import MinioObjectStore
    from backend.infrastructure.postgres.database import Database
    from backend.infrastructure.postgres.models import UserModel, WorkspaceModel
    from backend.infrastructure.postgres.schema import ensure_database_schema
    from backend.infrastructure.redis.queue import RedisTaskQueue
    from backend.infrastructure.sse.service import TaskEventStore, TaskEventStream
    from backend.models.runtime import ModelRuntimeService, OllamaRuntime
    from evaluation.dashboard import OfflineEvaluationDashboard
    from evaluation.hitl import StagingRegistry

    database = Database(settings.database_url)
    ensure_database_schema(database.engine)
    with database.session_factory() as session:
        if session.get(UserModel, LOCAL_USER_ID) is None:
            session.add(
                UserModel(
                    id=LOCAL_USER_ID,
                    email="local@paperagent.test",
                    name="本地用户",
                )
            )
        if session.get(WorkspaceModel, workspace_id) is None:
            session.add(
                WorkspaceModel(
                    id=workspace_id,
                    user_id=LOCAL_USER_ID,
                    name="PaperAgent 本地工作区",
                )
            )
        session.commit()
    redis = Redis.from_url(settings.redis_url)
    queue = RedisTaskQueue(redis, database.session_factory)
    event_stream = TaskEventStream(TaskEventStore(database.session_factory, redis))
    object_store = MinioObjectStore(
        Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
        ),
        database.session_factory,
        workspace_id,
        settings.minio_bucket_prefix,
    )
    dashboard_path = Path(
        os.getenv(
            "EVALUATION_DASHBOARD_PATH",
            "evaluation/reports/p03_dashboard_v1/cases.jsonl",
        )
    )

    def database_ready() -> bool:
        with database.session_factory() as session:
            return cast(int | None, session.scalar(text("SELECT 1"))) == 1

    return ApiContainer(
        request_id_generator=StaticUUIDGenerator(),
        trace_id_generator=StaticUUIDGenerator(),
        clock=SystemClock(),
        task_queue=queue,
        event_stream=event_stream,
        object_store=object_store,
        paper_agent=PaperAgentApplication(
            database.session_factory,
            object_store,
            queue,
        ),
        model_runtime=ModelRuntimeService(
            database.session_factory,
            OllamaRuntime(settings.ollama_endpoint),
        ),
        hitl_registry=StagingRegistry(
            Path(os.getenv("HITL_STAGING_ROOT", "evaluation/staging"))
        ),
        evaluation_dashboard=(
            OfflineEvaluationDashboard.from_jsonl(dashboard_path)
            if dashboard_path.exists()
            else None
        ),
        readiness_checks=(database_ready, lambda: bool(redis.ping())),
    )
