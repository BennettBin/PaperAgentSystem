"""Single-file paper reader sub Agent."""

import asyncio
from dataclasses import dataclass
from time import monotonic
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from core.errors import ErrorCode, ProjectError
from core.ports.observability import TraceWriter


class PaperEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(min_length=1)
    field: str = Field(min_length=1)
    quote: str = Field(min_length=1)
    page: int = Field(ge=1)


class PaperCard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    research_question: str
    methodology: str
    datasets: list[str]
    metrics: list[str]
    results: list[str]
    contributions: list[str]
    limitations: list[str]
    evidence: list[PaperEvidence]
    missing_fields: list[str]


class PaperReaderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_id: str = Field(min_length=1)


class PaperReaderBackend(Protocol):
    async def read(
        self,
        *,
        workspace_id: str,
        file_id: str,
        model_profile: str,
        allowed_tools: frozenset[str],
        max_steps: int,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class PaperReaderScope:
    workspace_id: str
    parent_task_id: str
    child_task_id: str
    assigned_file_id: str
    trace_id: str
    depth: int = 1


@dataclass(frozen=True, slots=True)
class PaperReaderBudget:
    max_steps: int = 8
    timeout_seconds: float = 120.0


@dataclass(frozen=True, slots=True)
class PaperReaderResult:
    child_task_id: str
    file_id: str
    model_profile: str
    card: PaperCard
    duration_ms: int


class PaperReaderAgent:
    name = "paper_reader_agent"
    version = "1.0.0"
    model_profile = "paper_reader_v1"
    allowed_tools = frozenset({"parse_document", "get_document_section", "verify_claim"})

    def __init__(
        self,
        backend: PaperReaderBackend,
        trace_writer: TraceWriter,
        budget: PaperReaderBudget | None = None,
    ) -> None:
        self._backend = backend
        self._traces = trace_writer
        self._budget = budget or PaperReaderBudget()

    async def execute(
        self,
        scope: PaperReaderScope,
        request: PaperReaderRequest,
    ) -> PaperReaderResult:
        if scope.depth > 1:
            raise ProjectError(
                ErrorCode.FAILED_PRECONDITION,
                "Sub Agent nesting depth cannot exceed one",
            )
        if request.file_id != scope.assigned_file_id:
            raise ProjectError(
                ErrorCode.PERMISSION_DENIED,
                "paper_reader_agent can only access its assigned file",
                {"requested_file_id": request.file_id},
            )
        started = monotonic()
        error: str | None = None
        try:
            raw = await asyncio.wait_for(
                self._backend.read(
                    workspace_id=scope.workspace_id,
                    file_id=scope.assigned_file_id,
                    model_profile=self.model_profile,
                    allowed_tools=self.allowed_tools,
                    max_steps=self._budget.max_steps,
                ),
                timeout=self._budget.timeout_seconds,
            )
            card = PaperCard.model_validate(raw)
            return PaperReaderResult(
                child_task_id=scope.child_task_id,
                file_id=scope.assigned_file_id,
                model_profile=self.model_profile,
                card=card,
                duration_ms=int((monotonic() - started) * 1000),
            )
        except TimeoutError as exc:
            error = "paper_reader_agent timed out"
            raise ProjectError(
                ErrorCode.DEADLINE_EXCEEDED,
                error,
                {"child_task_id": scope.child_task_id},
                cause=exc,
            ) from exc
        except Exception as exc:
            error = str(exc)
            raise
        finally:
            await self._traces.write_trace(
                scope.trace_id,
                "subagent.paper_reader",
                {
                    "agent_name": self.name,
                    "agent_version": self.version,
                    "model_profile": self.model_profile,
                    "parent_task_id": scope.parent_task_id,
                    "child_task_id": scope.child_task_id,
                    "file_id": scope.assigned_file_id,
                    "max_steps": self._budget.max_steps,
                    "user_message_emitted": False,
                },
                duration_ms=int((monotonic() - started) * 1000),
                error=error,
            )
