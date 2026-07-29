from backend.core.errors import ErrorCategory, ErrorCode, ProjectError
from backend.infrastructure.redis.queue import _should_retry


def test_queue_does_not_retry_terminal_project_error() -> None:
    error = ProjectError(
        ErrorCode.GENERATION_FAILED,
        "A required multi-Agent role failed",
    )

    assert not _should_retry(error)


def test_queue_retries_explicit_transient_and_unknown_failures() -> None:
    transient = ProjectError(
        ErrorCode.UNAVAILABLE,
        "model gateway unavailable",
        category=ErrorCategory.RETRYABLE,
    )

    assert _should_retry(transient)
    assert _should_retry(RuntimeError("unexpected worker failure"))
