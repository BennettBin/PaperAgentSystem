"""Production local worker that consumes PaperAgent Redis queues."""

from __future__ import annotations

import asyncio
import os
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from minio import Minio
from redis import Redis

from apps.api.product_service import (
    LOCAL_WORKSPACE_ID,
    PaperAgentProcessor,
)
from infrastructure.config import InfrastructureSettings
from infrastructure.fake.llm_clients import FakeEmbeddingClient, FakeRerankerClient
from infrastructure.minio.object_store import MinioObjectStore
from infrastructure.postgres.database import Database
from infrastructure.redis.queue import RedisTaskQueue
from infrastructure.sse.service import TaskEventStore
from models.runtime import (
    ModelRuntimeService,
    OllamaRuntime,
    RuntimeSelectedLLMClient,
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


def main() -> None:
    settings = InfrastructureSettings()
    database = Database(settings.database_url)
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
    processor = PaperAgentProcessor(
        database.session_factory,
        object_store,
        FakeEmbeddingClient(),
        FakeRerankerClient(),
        llm,
        TaskEventStore(database.session_factory, redis),
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


if __name__ == "__main__":
    main()
