import json

import pytest

from core.errors import ErrorCode, ProjectError
from infrastructure.fake.llm_clients import FakeLLMClient
from infrastructure.fake.observability import FakeTraceWriter
from models.client import OpenAICompatibleLLMClient, ProfiledLLMClient
from models.registry import (
    InMemoryModelRegistry,
    ModelProfileConfig,
    ModelVersionManifest,
    default_model_registry,
)


def profile(
    name: str,
    version: str,
    *,
    fallback: str | None = None,
) -> ModelProfileConfig:
    return ModelProfileConfig(
        profile_id_value=name,
        name_value=name,
        status_value=name,
        context_length_value=8192,
        max_tokens_value=2048,
        model_version_id=version,
        fallback_profile=fallback,
    )


@pytest.mark.asyncio
async def test_registry_supports_base_model_without_adapters() -> None:
    version = ModelVersionManifest(
        version_id="base-1.7b-v1",
        serving_model="paperagent-1.7b",
        base_model="paperagent-1.7b",
    )
    registry = InMemoryModelRegistry(
        profiles=[profile("development", version.version_id)],
        versions=[version],
        default_profile="development",
    )

    selected = await registry.resolve("development")

    assert selected.version.sft_adapter is None
    assert selected.version.rl_adapter is None
    assert selected.version.physical_path is None


@pytest.mark.asyncio
async def test_bundled_registry_has_development_evaluation_and_production_profiles() -> None:
    registry = default_model_registry()

    names = {item.name for item in await registry.list_profiles()}

    assert {"development", "evaluation", "production"} <= names


@pytest.mark.asyncio
async def test_profile_switch_does_not_change_call_site() -> None:
    versions = [
        ModelVersionManifest("small", "small-model", "base-1.7b"),
        ModelVersionManifest("large", "large-model", "base-4b"),
    ]
    registry = InMemoryModelRegistry(
        profiles=[
            profile("development", "small"),
            profile("production", "large"),
        ],
        versions=versions,
        default_profile="development",
    )
    clients = {
        "small": FakeLLMClient(),
        "large": FakeLLMClient(),
    }
    gateway = ProfiledLLMClient(registry, lambda resolved: clients[resolved.version.version_id])

    assert "Fake response" in await gateway.for_profile("development").generate("hello")
    assert "Fake response" in await gateway.for_profile("production").generate("hello")
    assert clients["small"].call_count == 1
    assert clients["large"].call_count == 1


@pytest.mark.asyncio
async def test_unavailable_model_uses_declared_fallback_and_records_versions() -> None:
    registry = InMemoryModelRegistry(
        profiles=[
            profile("production", "large", fallback="development"),
            profile("development", "small"),
        ],
        versions=[
            ModelVersionManifest("large", "large-model", "base-4b", sft_adapter="sft-v2"),
            ModelVersionManifest("small", "small-model", "base-1.7b"),
        ],
        default_profile="development",
    )
    trace = FakeTraceWriter()
    gateway = ProfiledLLMClient(
        registry,
        lambda resolved: FakeLLMClient(should_fail=resolved.version.version_id == "large"),
        trace_writer=trace,
        trace_id_factory=lambda: "trace-1",
    )

    result = await gateway.for_profile("production").generate("hello")

    assert "Fake response" in result
    assert trace.traces[-1]["data"]["requested_profile"] == "production"
    assert trace.traces[-1]["data"]["effective_profile"] == "development"
    assert trace.traces[-1]["data"]["base_model"] == "base-1.7b"


@pytest.mark.asyncio
async def test_unavailable_model_without_fallback_is_explicit() -> None:
    registry = InMemoryModelRegistry(
        profiles=[profile("production", "large")],
        versions=[ModelVersionManifest("large", "large-model", "base-4b")],
        default_profile="production",
    )
    gateway = ProfiledLLMClient(registry, lambda _: FakeLLMClient(should_fail=True))

    with pytest.raises(ProjectError) as exc:
        await gateway.for_profile("production").generate("hello")

    assert exc.value.code is ErrorCode.MODEL_NOT_AVAILABLE
    assert exc.value.details["profile"] == "production"


@pytest.mark.asyncio
async def test_openai_compatible_client_parses_chat_completion() -> None:
    captured: dict = {}

    async def post(url: str, headers: dict, payload: dict, timeout: float) -> dict:
        captured.update(url=url, headers=headers, payload=payload, timeout=timeout)
        return {"choices": [{"message": {"content": json.dumps({"ok": True})}}]}

    client = OpenAICompatibleLLMClient(
        base_url="http://model-service/v1",
        api_key="secret",
        model="logical-model",
        post_json=post,
    )

    result = await client.generate_with_schema(
        "return json",
        response_schema={"type": "object"},
    )

    assert json.loads(result) == {"ok": True}
    assert captured["url"].endswith("/chat/completions")
    assert captured["payload"]["response_format"]["type"] == "json_schema"
    assert captured["headers"]["Authorization"] == "Bearer secret"
