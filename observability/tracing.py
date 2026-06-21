"""OpenTelemetry-compatible persistent spans with safe attributes."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from core.ports.observability import TraceWriter
from infrastructure.postgres.models import TraceSpanModel

SENSITIVE_KEYS = {
    "prompt",
    "response",
    "content",
    "paper_text",
    "api_key",
    "authorization",
    "secret",
    "password",
}


@dataclass(frozen=True, slots=True)
class TraceSpan:
    span_id: str
    trace_id: str
    task_id: str | None
    parent_span_id: str | None
    span_name: str
    sequence: int
    data: dict[str, Any]
    duration_ms: int
    error: str | None


class SqlAlchemyTraceWriter(TraceWriter):
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sessions = session_factory

    async def write_trace(
        self,
        trace_id: str,
        span_name: str,
        data: dict,
        parent_span_id: str | None = None,
        duration_ms: int = 0,
        error: str | None = None,
    ) -> None:
        with self._sessions() as session:
            sequence = (
                session.scalar(
                    select(func.max(TraceSpanModel.sequence)).where(
                        TraceSpanModel.trace_id == trace_id
                    )
                )
                or 0
            ) + 1
            safe = _redact(data)
            session.add(
                TraceSpanModel(
                    span_id=uuid4().hex,
                    trace_id=trace_id,
                    task_id=str(data.get("task_id")) if data.get("task_id") else None,
                    parent_span_id=parent_span_id,
                    span_name=span_name,
                    sequence=sequence,
                    data=safe,
                    duration_ms=duration_ms,
                    error=error,
                )
            )
            session.commit()

    async def write_model_call(
        self,
        trace_id: str,
        model_id: str,
        prompt: str,
        response: str,
        tokens_in: int,
        tokens_out: int,
        latency_ms: int,
    ) -> None:
        await self.write_trace(
            trace_id,
            "model.call",
            {
                "model_id": model_id,
                "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                "response_sha256": hashlib.sha256(response.encode()).hexdigest(),
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
            },
            duration_ms=latency_ms,
        )


class TaskTraceService:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sessions = session_factory

    def reconstruct(self, task_id: str) -> list[TraceSpan]:
        with self._sessions() as session:
            models = session.scalars(
                select(TraceSpanModel)
                .where(TraceSpanModel.task_id == task_id)
                .order_by(TraceSpanModel.sequence, TraceSpanModel.created_at)
            ).all()
            return [
                TraceSpan(
                    span_id=model.span_id,
                    trace_id=model.trace_id,
                    task_id=model.task_id,
                    parent_span_id=model.parent_span_id,
                    span_name=model.span_name,
                    sequence=model.sequence,
                    data=model.data,
                    duration_ms=model.duration_ms,
                    error=model.error,
                )
                for model in models
            ]

    def critical_chain_complete(self, task_id: str) -> bool:
        names = {span.span_name for span in self.reconstruct(task_id)}
        required_groups = (
            {"api.request", "task.started"},
            {"requirement.check"},
            {"skill.activate"},
            {"plan.created"},
            {"tool.invoke", "subagent.paper_reader"},
            {"model.call"},
            {"memory.retrieve"},
            {"workspace.access"},
            {"rag.retrieve"},
            {"verification.complete"},
            {"task.completed"},
        )
        return all(bool(names & group) for group in required_groups)


def _redact(value: Any, key: str = "") -> Any:
    if key.casefold() in SENSITIVE_KEYS:
        serialized = str(value)
        return {
            "redacted": True,
            "sha256": hashlib.sha256(serialized.encode()).hexdigest(),
            "length": len(serialized),
        }
    if isinstance(value, dict):
        return {str(item_key): _redact(item, str(item_key)) for item_key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value
