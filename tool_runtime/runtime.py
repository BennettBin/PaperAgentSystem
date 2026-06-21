"""Typed Tool runtime with policy, idempotency, bounded output and Trace."""

from __future__ import annotations

import asyncio
import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from time import monotonic
from typing import Any, Generic, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from core.errors import ErrorCategory, ErrorCode, ProjectError
from core.ports.observability import TraceWriter

InputT = TypeVar("InputT", bound=BaseModel)
OutputT = TypeVar("OutputT", bound=BaseModel)


@dataclass(frozen=True, slots=True)
class ToolContext:
    workspace_id: str
    user_id: str
    conversation_id: str
    task_id: str
    trace_id: str
    permissions: frozenset[str]
    allowed_tools: frozenset[str]
    confirmed_tools: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class ToolPolicy:
    permission: str
    timeout_seconds: float = 30.0
    max_retries: int = 0
    retryable_exceptions: tuple[type[Exception], ...] = (ConnectionError,)
    side_effect: str = "read"
    confirmation_required: bool = False


class ToolDefinition(ABC, Generic[InputT, OutputT]):
    name: str
    description: str
    input_model: type[InputT]
    output_model: type[OutputT]
    policy: ToolPolicy

    @abstractmethod
    async def execute(self, context: ToolContext, arguments: InputT) -> OutputT:
        """Execute with trusted context and validated model arguments."""


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition[Any, Any]] = {}

    def register(self, tool: ToolDefinition[Any, Any]) -> None:
        if tool.name in self._tools:
            raise ProjectError(ErrorCode.ALREADY_EXISTS, f"Tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> ToolDefinition[Any, Any] | None:
        return self._tools.get(name)

    def list_all(self) -> list[ToolDefinition[Any, Any]]:
        return list(self._tools.values())


class IdempotencyStore(Protocol):
    async def get(self, key: str) -> ToolInvocationResult | None: ...
    async def put(self, key: str, value: ToolInvocationResult) -> None: ...


class DataRefStore(Protocol):
    async def write(self, workspace_id: str, task_id: str, payload: bytes) -> str: ...


@dataclass(frozen=True, slots=True)
class ToolInvocationResult:
    tool_name: str
    output: dict[str, Any] | None
    data_ref: str | None
    truncated: bool
    attempts: int
    idempotency_replay: bool = False


class InMemoryIdempotencyStore:
    def __init__(self) -> None:
        self._values: dict[str, ToolInvocationResult] = {}

    async def get(self, key: str) -> ToolInvocationResult | None:
        return self._values.get(key)

    async def put(self, key: str, value: ToolInvocationResult) -> None:
        self._values[key] = value


class InMemoryDataRefStore:
    def __init__(self) -> None:
        self._values: dict[str, bytes] = {}

    async def write(self, workspace_id: str, task_id: str, payload: bytes) -> str:
        digest = hashlib.sha256(payload).hexdigest()
        key = f"data:{workspace_id}:{task_id}:{digest}"
        self._values[key] = payload
        return key

    async def read(self, key: str) -> bytes | None:
        return self._values.get(key)


class ToolRuntime:
    PROTECTED_FIELDS = frozenset(
        {
            "workspace_id",
            "user_id",
            "conversation_id",
            "task_id",
            "trace_id",
            "permissions",
            "allowed_tools",
            "confirmed_tools",
        }
    )

    def __init__(
        self,
        registry: ToolRegistry,
        *,
        idempotency_store: IdempotencyStore,
        data_ref_store: DataRefStore,
        trace_writer: TraceWriter,
        max_inline_bytes: int = 64 * 1024,
    ) -> None:
        self._registry = registry
        self._idempotency = idempotency_store
        self._data_refs = data_ref_store
        self._traces = trace_writer
        self._max_inline_bytes = max_inline_bytes

    async def invoke(
        self,
        tool_name: str,
        raw_arguments: dict[str, Any],
        context: ToolContext,
        idempotency_key: str,
    ) -> ToolInvocationResult:
        started = monotonic()
        error: str | None = None
        attempts = 0
        try:
            cache_key = self._cache_key(context, idempotency_key)
            cached = await self._idempotency.get(cache_key)
            if cached is not None:
                return replace(cached, idempotency_replay=True)
            tool = self._registry.get(tool_name)
            if tool is None:
                raise ProjectError(ErrorCode.TOOL_NOT_FOUND, f"Tool not found: {tool_name}")
            self._authorize(tool, tool_name, raw_arguments, context)
            try:
                arguments = tool.input_model.model_validate(raw_arguments)
            except ValidationError as exc:
                raise ProjectError(
                    ErrorCode.INVALID_ARGUMENT,
                    "Tool arguments failed schema validation",
                    {"tool_name": tool_name, "errors": exc.errors(include_input=False)},
                ) from exc
            output: BaseModel | None = None
            for attempt in range(tool.policy.max_retries + 1):
                attempts = attempt + 1
                try:
                    output = await asyncio.wait_for(
                        tool.execute(context, arguments),
                        timeout=tool.policy.timeout_seconds,
                    )
                    break
                except TimeoutError as exc:
                    raise ProjectError(
                        ErrorCode.DEADLINE_EXCEEDED,
                        f"Tool timed out: {tool_name}",
                        {"tool_name": tool_name, "attempt": attempts},
                        cause=exc,
                        category=ErrorCategory.TIMEOUT,
                    ) from exc
                except tool.policy.retryable_exceptions:
                    if attempt >= tool.policy.max_retries:
                        raise ProjectError(
                            ErrorCode.UNAVAILABLE,
                            f"Tool failed after retries: {tool_name}",
                            {"tool_name": tool_name, "attempts": attempts},
                            category=ErrorCategory.RETRYABLE,
                        )
            if output is None:
                raise ProjectError(ErrorCode.INTERNAL_ERROR, "Tool returned no output")
            try:
                validated = tool.output_model.model_validate(output)
            except ValidationError as exc:
                raise ProjectError(
                    ErrorCode.INTERNAL_ERROR,
                    "Tool output failed schema validation",
                    {"tool_name": tool_name, "errors": exc.errors(include_input=False)},
                    cause=exc,
                    category=ErrorCategory.SYSTEM,
                ) from exc
            result = await self._bound_output(tool_name, validated, context, attempts)
            await self._idempotency.put(cache_key, result)
            return result
        except Exception as exc:
            error = str(exc)
            raise
        finally:
            await self._traces.write_trace(
                context.trace_id,
                "tool.invoke",
                {
                    "tool_name": tool_name,
                    "task_id": context.task_id,
                    "workspace_id": context.workspace_id,
                    "attempts": attempts,
                },
                duration_ms=int((monotonic() - started) * 1000),
                error=error,
            )

    @classmethod
    def _authorize(
        cls,
        tool: ToolDefinition[Any, Any],
        tool_name: str,
        arguments: dict[str, Any],
        context: ToolContext,
    ) -> None:
        injected = cls.PROTECTED_FIELDS & set(arguments)
        if injected:
            raise ProjectError(
                ErrorCode.PERMISSION_DENIED,
                "System-injected Tool fields cannot be supplied by the caller",
                {"fields": sorted(injected)},
                category=ErrorCategory.SECURITY,
            )
        if tool_name not in context.allowed_tools:
            raise ProjectError(
                ErrorCode.PERMISSION_DENIED,
                f"Tool is not allowed by the active Skill: {tool_name}",
            )
        if tool.policy.permission not in context.permissions:
            raise ProjectError(
                ErrorCode.PERMISSION_DENIED,
                f"Missing Tool permission: {tool.policy.permission}",
            )
        if tool.policy.confirmation_required and tool_name not in context.confirmed_tools:
            raise ProjectError(
                ErrorCode.FAILED_PRECONDITION,
                f"Tool requires explicit confirmation: {tool_name}",
            )

    async def _bound_output(
        self,
        tool_name: str,
        output: BaseModel,
        context: ToolContext,
        attempts: int,
    ) -> ToolInvocationResult:
        payload = output.model_dump_json().encode("utf-8")
        if len(payload) <= self._max_inline_bytes:
            return ToolInvocationResult(
                tool_name=tool_name,
                output=output.model_dump(mode="json"),
                data_ref=None,
                truncated=False,
                attempts=attempts,
            )
        data_ref = await self._data_refs.write(
            context.workspace_id,
            context.task_id,
            payload,
        )
        return ToolInvocationResult(
            tool_name=tool_name,
            output=None,
            data_ref=data_ref,
            truncated=True,
            attempts=attempts,
        )

    @staticmethod
    def _cache_key(context: ToolContext, idempotency_key: str) -> str:
        if not idempotency_key.strip():
            raise ProjectError(ErrorCode.INVALID_ARGUMENT, "idempotency_key is required")
        return f"{context.workspace_id}:{context.task_id}:{idempotency_key}"
