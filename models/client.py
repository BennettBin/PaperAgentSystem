"""OpenAI-compatible and profile-routed LLM clients."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from time import monotonic
from typing import Any
from urllib.request import Request, urlopen
from uuid import uuid4

from core.errors import ErrorCategory, ErrorCode, ProjectError
from core.ports.llm_client import LLMClient
from core.ports.observability import TraceWriter
from models.registry import InMemoryModelRegistry, ResolvedModelProfile

PostJson = Callable[[str, dict[str, str], dict[str, Any], float], Awaitable[dict[str, Any]]]
ClientFactory = Callable[[ResolvedModelProfile], LLMClient]


class OpenAICompatibleLLMClient(LLMClient):
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        *,
        timeout_seconds: float = 60.0,
        post_json: PostJson | None = None,
        extra_body: dict[str, Any] | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._timeout = timeout_seconds
        self._post_json = post_json or self._httpx_post
        self._extra_body = dict(extra_body or {})

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        top_p: float = 0.95,
        stop_sequences: list[str] | None = None,
    ) -> str:
        return await self._complete(
            prompt,
            system_prompt,
            max_tokens,
            temperature,
            top_p,
            stop_sequences,
        )

    async def generate_with_schema(
        self,
        prompt: str,
        system_prompt: str | None = None,
        response_schema: dict | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.7,
    ) -> str:
        response_format = None
        if response_schema is not None:
            response_format = {
                "type": "json_schema",
                "json_schema": {"name": "response", "schema": response_schema},
            }
        return await self._complete(
            prompt,
            system_prompt,
            max_tokens,
            temperature,
            0.95,
            None,
            response_format,
        )

    async def _complete(
        self,
        prompt: str,
        system_prompt: str | None,
        max_tokens: int,
        temperature: float,
        top_p: float,
        stop: list[str] | None,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": top_p,
            **self._extra_body,
        }
        if stop:
            payload["stop"] = stop
        if response_format:
            payload["response_format"] = response_format
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        try:
            data = await self._post_json(
                f"{self._base_url}/chat/completions",
                headers,
                payload,
                self._timeout,
            )
            content = str(data["choices"][0]["message"]["content"]).strip()
            if not content:
                raise ValueError("Model response content is empty")
            return content
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ProjectError(
                ErrorCode.GENERATION_FAILED,
                "Model service returned an invalid chat completion",
                cause=exc,
                category=ErrorCategory.SYSTEM,
            ) from exc

    @staticmethod
    async def _httpx_post(
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        timeout: float,
    ) -> dict[str, Any]:
        def send() -> dict[str, Any]:
            request = Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urlopen(request, timeout=timeout) as response:
                value: Any = json.loads(response.read().decode("utf-8"))
                if not isinstance(value, dict):
                    raise TypeError("Model response must be a JSON object")
                return value

        return await asyncio.to_thread(send)


class _BoundProfileClient(LLMClient):
    def __init__(self, gateway: ProfiledLLMClient, profile: str) -> None:
        self._gateway = gateway
        self._profile = profile

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        top_p: float = 0.95,
        stop_sequences: list[str] | None = None,
    ) -> str:
        return await self._gateway._call(
            self._profile,
            "generate",
            prompt,
            {
                "system_prompt": system_prompt,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "top_p": top_p,
                "stop_sequences": stop_sequences,
            },
        )

    async def generate_with_schema(
        self,
        prompt: str,
        system_prompt: str | None = None,
        response_schema: dict | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.7,
    ) -> str:
        return await self._gateway._call(
            self._profile,
            "generate_with_schema",
            prompt,
            {
                "system_prompt": system_prompt,
                "response_schema": response_schema,
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
        )


class ProfiledLLMClient:
    """Selects models by logical profile and applies one declared fallback."""

    def __init__(
        self,
        registry: InMemoryModelRegistry,
        client_factory: ClientFactory,
        *,
        trace_writer: TraceWriter | None = None,
        trace_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._registry = registry
        self._client_factory = client_factory
        self._trace_writer = trace_writer
        self._trace_id_factory = trace_id_factory or (lambda: str(uuid4()))

    def for_profile(self, profile: str) -> LLMClient:
        return _BoundProfileClient(self, profile)

    async def _call(
        self,
        requested_profile: str,
        method: str,
        prompt: str,
        kwargs: dict[str, Any],
    ) -> str:
        requested = await self._registry.resolve(requested_profile)
        started = monotonic()
        error: Exception | None = None
        effective = requested
        try:
            response = await getattr(self._client_factory(requested), method)(prompt, **kwargs)
            return str(response)
        except Exception as exc:
            error = exc
            fallback = requested.profile.fallback_profile
            if fallback:
                effective = await self._registry.resolve(fallback)
                try:
                    response = await getattr(self._client_factory(effective), method)(
                        prompt, **kwargs
                    )
                    return str(response)
                except Exception as fallback_exc:
                    error = fallback_exc
            raise ProjectError(
                ErrorCode.MODEL_NOT_AVAILABLE,
                f"Model call failed for profile: {requested_profile}",
                {"profile": requested_profile, "fallback": fallback},
                cause=error,
                category=ErrorCategory.RETRYABLE,
            ) from error
        finally:
            if self._trace_writer:
                await self._trace_writer.write_trace(
                    self._trace_id_factory(),
                    "model.call",
                    {
                        "requested_profile": requested_profile,
                        "effective_profile": effective.profile.name,
                        "profile_version": effective.version.profile_version,
                        "model_version_id": effective.version.version_id,
                        "base_model": effective.version.base_model,
                        "sft_adapter": effective.version.sft_adapter,
                        "rl_adapter": effective.version.rl_adapter,
                    },
                    duration_ms=int((monotonic() - started) * 1000),
                    error=str(error) if error and effective is requested else None,
                )
