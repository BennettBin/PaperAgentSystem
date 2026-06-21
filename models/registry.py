"""Model profile registry without physical model paths."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from core.errors import ErrorCategory, ErrorCode, ProjectError
from core.ports.registry import ModelProfile, ModelRegistry


@dataclass(frozen=True, slots=True)
class ModelVersionManifest:
    """Deployable model identity recorded in traces and evaluation reports."""

    version_id: str
    serving_model: str
    base_model: str
    sft_adapter: str | None = None
    rl_adapter: str | None = None
    profile_version: str = "1"
    metadata: dict[str, Any] = field(default_factory=dict)
    physical_path: None = field(default=None, init=False, repr=False)


@dataclass(frozen=True, slots=True)
class ModelProfileConfig(ModelProfile):
    profile_id_value: str
    name_value: str
    status_value: str
    context_length_value: int
    max_tokens_value: int
    model_version_id: str
    generation_config: dict[str, Any] = field(default_factory=dict)
    fallback_profile: str | None = None

    @property
    def profile_id(self) -> str:
        return self.profile_id_value

    @property
    def name(self) -> str:
        return self.name_value

    @property
    def status(self) -> str:
        return self.status_value

    @property
    def context_length(self) -> int:
        return self.context_length_value

    @property
    def max_tokens(self) -> int:
        return self.max_tokens_value

    @property
    def config(self) -> dict[str, Any]:
        return dict(self.generation_config)


@dataclass(frozen=True, slots=True)
class ResolvedModelProfile:
    profile: ModelProfileConfig
    version: ModelVersionManifest


class InMemoryModelRegistry(ModelRegistry):
    """Registry suitable for configuration loading and deterministic tests."""

    def __init__(
        self,
        profiles: list[ModelProfileConfig] | None = None,
        versions: list[ModelVersionManifest] | None = None,
        default_profile: str = "development",
    ) -> None:
        self._profiles = {item.name: item for item in profiles or []}
        self._versions = {item.version_id: item for item in versions or []}
        self._default_profile = default_profile

    async def get_profile(self, profile_name: str) -> ModelProfileConfig | None:
        return self._profiles.get(profile_name)

    async def list_profiles(self) -> list[ModelProfile]:
        return list(self._profiles.values())

    async def register_profile(self, profile: ModelProfile) -> None:
        if not isinstance(profile, ModelProfileConfig):
            raise TypeError("InMemoryModelRegistry requires ModelProfileConfig")
        if profile.model_version_id not in self._versions:
            raise ProjectError(
                ErrorCode.MODEL_NOT_AVAILABLE,
                f"Unknown model version: {profile.model_version_id}",
                {"model_version_id": profile.model_version_id},
            )
        self._profiles[profile.name] = profile

    async def register_version(self, version: ModelVersionManifest) -> None:
        self._versions[version.version_id] = version

    async def get_default_profile(self) -> ModelProfileConfig:
        profile = await self.get_profile(self._default_profile)
        if profile is None:
            raise self._unavailable(self._default_profile)
        return profile

    async def resolve(self, profile_name: str | None = None) -> ResolvedModelProfile:
        profile = (
            await self.get_profile(profile_name)
            if profile_name is not None
            else await self.get_default_profile()
        )
        if profile is None:
            raise self._unavailable(profile_name or self._default_profile)
        version = self._versions.get(profile.model_version_id)
        if version is None:
            raise self._unavailable(profile.name, profile.model_version_id)
        return ResolvedModelProfile(profile, version)

    @staticmethod
    def _unavailable(profile: str, version: str | None = None) -> ProjectError:
        return ProjectError(
            ErrorCode.MODEL_NOT_AVAILABLE,
            f"Model profile is unavailable: {profile}",
            {"profile": profile, "model_version_id": version},
            category=ErrorCategory.RETRYABLE,
        )


def default_model_registry() -> InMemoryModelRegistry:
    """Profiles run on base models even when no optional adapter is installed."""

    return load_model_registry(Path(__file__).with_name("registry.yaml"))


def load_model_registry(path: Path) -> InMemoryModelRegistry:
    """Load logical profiles and version manifests from configuration."""

    data = yaml.safe_load(path.read_text("utf-8"))
    versions = [ModelVersionManifest(**item) for item in data["versions"]]
    profiles = [
        ModelProfileConfig(
            profile_id_value=item["name"],
            name_value=item["name"],
            status_value=item["status"],
            context_length_value=item["context_length"],
            max_tokens_value=item["max_tokens"],
            model_version_id=item["model_version_id"],
            generation_config=item.get("generation_config", {}),
            fallback_profile=item.get("fallback_profile"),
        )
        for item in data["profiles"]
    ]
    return InMemoryModelRegistry(
        profiles=profiles,
        versions=versions,
        default_profile=data["default_profile"],
    )
