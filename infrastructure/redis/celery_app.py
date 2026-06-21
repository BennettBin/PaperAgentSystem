from celery import Celery  # type: ignore[import-untyped]
from kombu import Queue  # type: ignore[import-untyped]


def create_celery_app(broker_url: str, result_backend: str) -> Celery:
    app = Celery("paperagent", broker=broker_url, backend=result_backend)
    app.conf.update(
        task_queues=(
            Queue("main_agent"),
            Queue("sub_agent"),
            Queue("document_parse"),
            Queue("memory_summary"),
            Queue("dead_letter"),
        ),
        task_routes={
            "paperagent.main_agent": {"queue": "main_agent"},
            "paperagent.sub_agent": {"queue": "sub_agent"},
            "paperagent.document_parse": {"queue": "document_parse"},
            "paperagent.memory_summary": {"queue": "memory_summary"},
        },
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        broker_transport_options={"visibility_timeout": 3600},
        task_default_retry_delay=1,
    )
    return app
