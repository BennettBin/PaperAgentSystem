"""Runtime model catalog, Ollama lifecycle checks and persistent selections."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol
from urllib.request import Request, urlopen

import yaml
from sqlalchemy.orm import Session, sessionmaker

from core.errors import ErrorCategory, ErrorCode, ProjectError
from core.ports.llm_client import LLMClient
from infrastructure.postgres.models import ModelRuntimeConfigModel
from models.client import OpenAICompatibleLLMClient

ModelRole = Literal["small", "large"]

DEFAULT_SMALL = {
    "model_id": "base-qwen3-1.7b",
    "display_name": "Qwen3 1.7B Base",
    "serving_model": "qwen3:1.7b",
    "role": "small",
    "stage": "base",
    "version": "base",
}
DEFAULT_LARGE = {
    "model_id": "base-qwen3.5-4b",
    "display_name": "Qwen3.5 4B Base",
    "serving_model": "qwen3.5:4b",
    "role": "large",
    "stage": "base",
    "version": "base",
}


class OllamaRuntimePort(Protocol):
    async def list_models(self) -> list[dict[str, Any]]: ...

    async def pull(self, model: str) -> None: ...

    async def probe(self, model: str) -> str: ...


@dataclass(frozen=True, slots=True)
class OllamaRuntime(OllamaRuntimePort):
    endpoint: str = "http://host.docker.internal:11434"
    timeout_seconds: float = 1800

    async def list_models(self) -> list[dict[str, Any]]:
        try:
            value = await self._request("GET", "/api/tags")
            return list(value.get("models", []))
        except Exception as exc:
            raise ProjectError(
                ErrorCode.MODEL_NOT_AVAILABLE,
                "无法连接本地 Ollama 服务",
                {"endpoint": self.endpoint},
                cause=exc,
                category=ErrorCategory.RETRYABLE,
            ) from exc

    async def pull(self, model: str) -> None:
        await self._request(
            "POST",
            "/api/pull",
            {"model": model, "stream": False},
            timeout=self.timeout_seconds,
        )

    async def probe(self, model: str) -> str:
        value = await self._request(
            "POST",
            "/v1/chat/completions",
            {
                "model": model,
                "messages": [{"role": "user", "content": "Respond only with OK. /no_think"}],
                "max_tokens": 64,
                "temperature": 0,
                "reasoning_effort": "none",
            },
            timeout=180,
        )
        try:
            content = str(value["choices"][0]["message"]["content"]).strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise ProjectError(
                ErrorCode.MODEL_NOT_AVAILABLE,
                f"模型 {model} 返回了无效响应",
                cause=exc,
            ) from exc
        if not content:
            raise ProjectError(
                ErrorCode.MODEL_NOT_AVAILABLE,
                f"模型 {model} 未返回可用文本",
            )
        return content

    async def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        def send() -> dict[str, Any]:
            request = Request(
                f"{self.endpoint.rstrip('/')}{path}",
                data=None if payload is None else json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method=method,
            )
            with urlopen(request, timeout=timeout or self.timeout_seconds) as response:
                result: Any = json.loads(response.read().decode("utf-8"))
                if not isinstance(result, dict):
                    raise TypeError("Ollama response must be an object")
                return result

        return await asyncio.to_thread(send)


class ModelRuntimeService:
    def __init__(
        self,
        sessions: sessionmaker[Session],
        ollama: OllamaRuntimePort,
        *,
        registry_path: Path | None = None,
    ) -> None:
        self._sessions = sessions
        self._ollama = ollama
        self._registry_path = registry_path or Path(__file__).with_name("registry.yaml")

    async def get_settings(self) -> dict[str, Any]:
        installed_models = await self._ollama.list_models()
        installed = {str(item["name"]): item for item in installed_models}
        catalog = self._catalog(installed_models)
        selected = self._selection()
        models = [
            {
                **item,
                "installed": item["serving_model"] in installed,
                "callable": item["serving_model"] in installed,
                "size_bytes": int(installed.get(item["serving_model"], {}).get("size", 0)),
                "parameter_size": installed.get(item["serving_model"], {})
                .get("details", {})
                .get("parameter_size"),
            }
            for item in catalog
        ]
        by_id = {item["model_id"]: item for item in models}
        selected_view = {
            role: by_id.get(value["model_id"], {**value, "installed": False, "callable": False})
            for role, value in selected.items()
        }
        return {
            "ollama_available": True,
            "selected": selected_view,
            "models": models,
        }

    async def check_base_model(self, role: ModelRole, model_name: str) -> dict[str, Any]:
        clean = _validate_model_name(model_name)
        installed = {str(item["name"]) for item in await self._ollama.list_models()}
        model = _custom_base(role, clean)
        available = clean in installed
        if available:
            await self._ollama.probe(clean)
        return {
            **model,
            "available": available,
            "requires_download": not available,
            "callable": available,
        }

    async def download_and_select(
        self, role: ModelRole, model_name: str
    ) -> dict[str, Any]:
        clean = _validate_model_name(model_name)
        installed = {str(item["name"]) for item in await self._ollama.list_models()}
        if clean not in installed:
            await self._ollama.pull(clean)
        await self._ollama.probe(clean)
        self._save_selection(role, _custom_base(role, clean))
        return await self.get_settings()

    async def select(self, role: ModelRole, model_id: str) -> dict[str, Any]:
        settings = await self.get_settings()
        candidate = next(
            (item for item in settings["models"] if item["model_id"] == model_id),
            None,
        )
        if candidate is None:
            raise ProjectError(ErrorCode.NOT_FOUND, f"模型版本不存在：{model_id}")
        if not candidate["installed"]:
            raise ProjectError(
                ErrorCode.MODEL_NOT_AVAILABLE,
                f"模型尚未下载：{candidate['serving_model']}",
                {"requires_download": True, "serving_model": candidate["serving_model"]},
            )
        await self._ollama.probe(str(candidate["serving_model"]))
        self._save_selection(role, _descriptor(candidate))
        return await self.get_settings()

    async def selected_descriptor(self, role: ModelRole) -> dict[str, Any]:
        return self._selection()[role]

    async def selected_client(self, role: ModelRole) -> LLMClient:
        selected = await self.selected_descriptor(role)
        return OpenAICompatibleLLMClient(
            f"{getattr(self._ollama, 'endpoint', 'http://host.docker.internal:11434')}/v1",
            "ollama",
            str(selected["serving_model"]),
            timeout_seconds=180,
            extra_body={"reasoning_effort": "none"},
        )

    def _selection(self) -> dict[str, dict[str, Any]]:
        with self._sessions() as session:
            config = session.get(ModelRuntimeConfigModel, "default")
            if config is None:
                config = ModelRuntimeConfigModel(
                    id="default",
                    small_model=dict(DEFAULT_SMALL),
                    large_model=dict(DEFAULT_LARGE),
                )
                session.add(config)
                session.commit()
            return {
                "small": dict(config.small_model),
                "large": dict(config.large_model),
            }

    def _save_selection(self, role: ModelRole, model: dict[str, Any]) -> None:
        with self._sessions() as session:
            config = session.get(ModelRuntimeConfigModel, "default")
            if config is None:
                config = ModelRuntimeConfigModel(
                    id="default",
                    small_model=dict(DEFAULT_SMALL),
                    large_model=dict(DEFAULT_LARGE),
                )
                session.add(config)
            if role == "small":
                config.small_model = _descriptor(model)
            else:
                config.large_model = _descriptor(model)
            session.commit()

    def _catalog(self, installed: list[dict[str, Any]]) -> list[dict[str, Any]]:
        catalog = [dict(DEFAULT_SMALL), dict(DEFAULT_LARGE)]
        known_names = {item["serving_model"] for item in catalog}
        for model in installed:
            name = str(model.get("name", "")).strip()
            capabilities = set(model.get("capabilities", []))
            if not name or (capabilities and "completion" not in capabilities):
                continue
            if name in known_names:
                continue
            role: ModelRole = _infer_role(
                str(model.get("details", {}).get("parameter_size", ""))
            )
            catalog.append(_custom_base(role, name))
            known_names.add(name)
        catalog.extend(self._trained_catalog())
        return catalog

    def _trained_catalog(self) -> list[dict[str, Any]]:
        data = yaml.safe_load(self._registry_path.read_text("utf-8"))
        result = []
        for version in data.get("versions", []):
            role: ModelRole = (
                "small" if "1.7" in str(version.get("base_model", "")) else "large"
            )
            for stage, field in (("sft", "sft_adapter"), ("rl", "rl_adapter")):
                adapter = version.get(field)
                if not adapter:
                    continue
                unique_name = f"{version['version_id']}-{stage}-{adapter}"
                result.append(
                    {
                        "model_id": unique_name,
                        "display_name": unique_name,
                        "serving_model": version["serving_model"],
                        "role": role,
                        "stage": stage,
                        "version": str(adapter),
                    }
                )
        return result


class RuntimeSelectedLLMClient(LLMClient):
    def __init__(self, runtime: ModelRuntimeService, role: ModelRole) -> None:
        self._runtime = runtime
        self._role = role

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        top_p: float = 0.95,
        stop_sequences: list[str] | None = None,
    ) -> str:
        client = await self._runtime.selected_client(self._role)
        return await client.generate(
            prompt,
            _without_thinking(system_prompt),
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
        client = await self._runtime.selected_client(self._role)
        return await client.generate_with_schema(
            prompt,
            _without_thinking(system_prompt),
            response_schema,
            max_tokens,
            temperature,
        )


def _infer_role(parameter_size: str) -> ModelRole:
    digits = "".join(char for char in parameter_size if char.isdigit() or char == ".")
    try:
        return "small" if float(digits or "4") < 4 else "large"
    except ValueError:
        return "large"


def _custom_base(role: ModelRole, name: str) -> dict[str, Any]:
    suffix = hashlib.sha256(name.encode("utf-8")).hexdigest()[:10]
    return {
        "model_id": f"base-ollama-{suffix}",
        "display_name": f"{name} Base",
        "serving_model": name,
        "role": role,
        "stage": "base",
        "version": "base",
    }


def _descriptor(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value[key]
        for key in (
            "model_id",
            "display_name",
            "serving_model",
            "role",
            "stage",
            "version",
        )
    }


def _validate_model_name(model: str) -> str:
    clean = model.strip()
    if not clean or len(clean) > 200:
        raise ProjectError(ErrorCode.INVALID_ARGUMENT, "模型名称无效")
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-/:")
    if any(char not in allowed for char in clean):
        raise ProjectError(ErrorCode.INVALID_ARGUMENT, "模型名称包含非法字符")
    return clean


def _without_thinking(system_prompt: str | None) -> str:
    prompt = system_prompt or ""
    return f"{prompt}\n/no_think".strip()
