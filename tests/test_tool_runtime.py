import asyncio

import pytest
from pydantic import BaseModel, Field

from core.errors import ErrorCode, ProjectError
from infrastructure.fake.observability import FakeTraceWriter
from tool_runtime import (
    InMemoryDataRefStore,
    InMemoryIdempotencyStore,
    ToolContext,
    ToolDefinition,
    ToolPolicy,
    ToolRegistry,
    ToolRuntime,
)


class EchoInput(BaseModel):
    text: str = Field(min_length=1)


class EchoOutput(BaseModel):
    text: str


class EchoTool(ToolDefinition[EchoInput, EchoOutput]):
    name = "echo"
    description = "Echo validated text."
    input_model = EchoInput
    output_model = EchoOutput
    policy = ToolPolicy(
        permission="workspace:read",
        timeout_seconds=0.05,
        max_retries=1,
    )

    def __init__(self) -> None:
        self.calls = 0
        self.fail_once = False

    async def execute(self, context: ToolContext, arguments: EchoInput) -> EchoOutput:
        self.calls += 1
        if self.fail_once and self.calls == 1:
            raise ConnectionError("temporary")
        return EchoOutput(text=arguments.text)


def runtime(tool: EchoTool | None = None, *, max_inline_bytes: int = 256):
    selected = tool or EchoTool()
    registry = ToolRegistry()
    registry.register(selected)
    traces = FakeTraceWriter()
    data_refs = InMemoryDataRefStore()
    return (
        selected,
        ToolRuntime(
            registry,
            idempotency_store=InMemoryIdempotencyStore(),
            data_ref_store=data_refs,
            trace_writer=traces,
            max_inline_bytes=max_inline_bytes,
        ),
        traces,
        data_refs,
    )


def context(**overrides) -> ToolContext:
    values = {
        "workspace_id": "ws-1",
        "user_id": "user-1",
        "conversation_id": "conv-1",
        "task_id": "task-1",
        "trace_id": "trace-1",
        "permissions": frozenset({"workspace:read"}),
        "allowed_tools": frozenset({"echo"}),
    }
    values.update(overrides)
    return ToolContext(**values)


@pytest.mark.asyncio
async def test_invalid_arguments_do_not_execute_tool() -> None:
    tool, service, _, _ = runtime()

    with pytest.raises(ProjectError) as exc:
        await service.invoke("echo", {"text": ""}, context(), "idem-1")

    assert exc.value.code is ErrorCode.INVALID_ARGUMENT
    assert tool.calls == 0


@pytest.mark.asyncio
async def test_system_injected_fields_are_rejected() -> None:
    tool, service, _, _ = runtime()

    with pytest.raises(ProjectError) as exc:
        await service.invoke(
            "echo",
            {"text": "ok", "workspace_id": "other"},
            context(),
            "idem-2",
        )

    assert exc.value.code is ErrorCode.PERMISSION_DENIED
    assert tool.calls == 0


@pytest.mark.asyncio
async def test_whitelist_and_permission_are_enforced() -> None:
    tool, service, _, _ = runtime()

    with pytest.raises(ProjectError) as blocked:
        await service.invoke(
            "echo",
            {"text": "ok"},
            context(allowed_tools=frozenset()),
            "idem-3",
        )
    with pytest.raises(ProjectError) as denied:
        await service.invoke(
            "echo",
            {"text": "ok"},
            context(permissions=frozenset()),
            "idem-4",
        )

    assert blocked.value.code is ErrorCode.PERMISSION_DENIED
    assert denied.value.code is ErrorCode.PERMISSION_DENIED
    assert tool.calls == 0


@pytest.mark.asyncio
async def test_retry_idempotency_and_trace() -> None:
    tool = EchoTool()
    tool.fail_once = True
    tool, service, traces, _ = runtime(tool)

    first = await service.invoke("echo", {"text": "ok"}, context(), "idem-5")
    second = await service.invoke("echo", {"text": "ok"}, context(), "idem-5")

    assert first.output == {"text": "ok"}
    assert second.output == first.output
    assert tool.calls == 2
    assert second.idempotency_replay
    assert traces.traces[-1]["span_name"] == "tool.invoke"
    assert traces.traces[-1]["data"]["tool_name"] == "echo"


@pytest.mark.asyncio
async def test_timeout_is_explicit() -> None:
    class SlowTool(EchoTool):
        async def execute(self, context: ToolContext, arguments: EchoInput) -> EchoOutput:
            self.calls += 1
            await asyncio.sleep(0.1)
            return EchoOutput(text=arguments.text)

    _, service, _, _ = runtime(SlowTool())

    with pytest.raises(ProjectError) as exc:
        await service.invoke("echo", {"text": "ok"}, context(), "idem-6")

    assert exc.value.code is ErrorCode.DEADLINE_EXCEEDED


@pytest.mark.asyncio
async def test_large_output_is_stored_as_data_ref() -> None:
    _, service, _, refs = runtime(max_inline_bytes=32)

    result = await service.invoke("echo", {"text": "x" * 100}, context(), "idem-7")

    assert result.truncated
    assert result.data_ref is not None
    assert await refs.read(result.data_ref) == b'{"text":"xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"}'


@pytest.mark.asyncio
async def test_confirmation_is_system_injected_for_high_risk_tool() -> None:
    class ConfirmedTool(EchoTool):
        policy = ToolPolicy(
            permission="workspace:read",
            confirmation_required=True,
        )

    _, service, _, _ = runtime(ConfirmedTool())
    with pytest.raises(ProjectError) as exc:
        await service.invoke("echo", {"text": "ok"}, context(), "confirm-1")
    result = await service.invoke(
        "echo",
        {"text": "ok"},
        context(confirmed_tools=frozenset({"echo"})),
        "confirm-2",
    )

    assert exc.value.code is ErrorCode.FAILED_PRECONDITION
    assert result.output == {"text": "ok"}


@pytest.mark.asyncio
async def test_retry_exhaustion_uses_unified_error() -> None:
    class FailingTool(EchoTool):
        async def execute(self, context: ToolContext, arguments: EchoInput) -> EchoOutput:
            self.calls += 1
            raise ConnectionError("still unavailable")

    tool, service, _, _ = runtime(FailingTool())

    with pytest.raises(ProjectError) as exc:
        await service.invoke("echo", {"text": "ok"}, context(), "retry-failed")

    assert exc.value.code is ErrorCode.UNAVAILABLE
    assert tool.calls == 2
