from typing import Any

from celery import Celery  # type: ignore[import-untyped]

from infrastructure.redis.queue import RedisTaskQueue


def register_worker_tasks(app: Celery, queue: RedisTaskQueue) -> None:
    for task_type, queue_name in {
        "main_agent": "main_agent",
        "sub_agent": "sub_agent",
        "document_parse": "document_parse",
        "memory_summary": "memory_summary",
    }.items():

        @app.task(
            name=f"paperagent.{task_type}",
            bind=True,
            autoretry_for=(Exception,),
            retry_backoff=True,
            retry_kwargs={"max_retries": 3},
            acks_late=True,
        )
        def consume(self: Any, selected_queue: str = queue_name) -> str | None:
            return queue.execute_next(selected_queue, timeout=1)
