"""Logical model profiles and OpenAI-compatible model clients."""

from backend.models.client import OpenAICompatibleLLMClient, ProfiledLLMClient
from backend.models.registry import (
    InMemoryModelRegistry,
    ModelProfileConfig,
    ModelVersionManifest,
    ResolvedModelProfile,
    default_model_registry,
    load_model_registry,
)

__all__ = [
    "InMemoryModelRegistry",
    "ModelProfileConfig",
    "ModelVersionManifest",
    "OpenAICompatibleLLMClient",
    "ProfiledLLMClient",
    "ResolvedModelProfile",
    "default_model_registry",
    "load_model_registry",
]
