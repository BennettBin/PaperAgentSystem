"""Versioned local embedding providers with bounded batching and safe fallback."""

from __future__ import annotations

import asyncio
import logging
import math
import threading
import time
from collections import OrderedDict
from collections.abc import Sequence
from typing import Any

from backend.core.ports.llm_client import EmbeddingClient, EmbeddingProfile

LOGGER = logging.getLogger(__name__)

HASH_PROFILE = EmbeddingProfile(
    provider="hash",
    model_name="multilingual-hash",
    model_version="v1",
    dimension=1024,
    max_length=0,
    normalized=True,
)


class EmbeddingUnavailableError(RuntimeError):
    """Raised for embedding work while a configured provider is unavailable."""


class BGEM3Embedding(EmbeddingClient):
    """Sentence-Transformers backed BGE-M3 dense embedding provider."""

    def __init__(
        self,
        *,
        model_name: str = "BAAI/bge-m3",
        model_version: str = "main",
        device: str = "auto",
        batch_size: int = 32,
        max_length: int = 512,
        use_fp16: bool = True,
        model: Any | None = None,
        torch_module: Any | None = None,
    ) -> None:
        if batch_size < 1:
            raise ValueError("Embedding batch size must be positive")
        if max_length < 1:
            raise ValueError("Embedding max length must be positive")
        self._batch_size = batch_size
        self._max_length = max_length
        self._lock = threading.Lock()
        load_started = time.perf_counter()
        torch = torch_module or _import_torch()
        self._torch = torch
        self._device = _resolve_device(torch, device)
        self._dtype = "float32"
        model_kwargs: dict[str, Any] = {}
        if self._device == "cuda" and use_fp16:
            model_kwargs["torch_dtype"] = torch.float16
            self._dtype = "float16"
        if model is None:
            try:
                import sentence_transformers  # type: ignore[import-not-found]
            except ImportError as exc:  # pragma: no cover - depends on optional runtime
                raise EmbeddingUnavailableError(
                    "sentence-transformers is required for BGE-M3"
                ) from exc
            model = sentence_transformers.SentenceTransformer(
                model_name,
                device=self._device,
                model_kwargs=model_kwargs,
                revision=model_version,
            )
        self._model = model
        self._model.max_seq_length = max_length
        self._model.eval()
        self._profile = EmbeddingProfile(
            provider="bge_m3",
            model_name=model_name,
            model_version=_resolved_model_version(model, model_version),
            dimension=1024,
            max_length=max_length,
            normalized=True,
        )
        LOGGER.info(
            "Embedding model loaded provider=%s model=%s version=%s device=%s "
            "dtype=%s load_seconds=%.3f",
            self._profile.provider,
            self._profile.model_name,
            self._profile.model_version,
            self._device,
            self._dtype,
            time.perf_counter() - load_started,
        )

    @property
    def profile(self) -> EmbeddingProfile:
        return self._profile

    async def embed(self, text: str) -> list[float]:
        started = time.perf_counter()
        result = (await self.embed_batch([text]))[0]
        LOGGER.info(
            "Query embedding completed provider=%s model=%s elapsed_ms=%.3f",
            self._profile.provider,
            self._profile.model_name,
            (time.perf_counter() - started) * 1000,
        )
        return result

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return await asyncio.to_thread(self._embed_batch_sync, texts)

    def _embed_batch_sync(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        unique, positions = _prepare_unique(texts)
        encoded: dict[str, list[float]] = {
            "": [0.0] * self._profile.dimension
        }
        pending = [text for text in unique if text]
        offset = 0
        selected_batch_size = min(self._batch_size, max(1, len(pending)))
        with self._lock, self._torch.inference_mode():
            while offset < len(pending):
                batch = pending[offset : offset + selected_batch_size]
                started = time.perf_counter()
                try:
                    values = self._model.encode(
                        batch,
                        batch_size=len(batch),
                        convert_to_numpy=True,
                        normalize_embeddings=True,
                        show_progress_bar=False,
                    )
                except Exception as exc:
                    if _is_out_of_memory(self._torch, exc) and selected_batch_size > 1:
                        previous = selected_batch_size
                        selected_batch_size = max(1, selected_batch_size // 2)
                        _empty_cuda_cache(self._torch, self._device)
                        LOGGER.warning(
                            "Embedding batch size degraded model=%s device=%s from=%d to=%d",
                            self._profile.model_name,
                            self._device,
                            previous,
                            selected_batch_size,
                        )
                        continue
                    raise
                elapsed = time.perf_counter() - started
                rows = values.tolist() if hasattr(values, "tolist") else list(values)
                if len(rows) != len(batch):
                    raise RuntimeError("Embedding model returned an unexpected batch size")
                for text, vector in zip(batch, rows):
                    normalized = [float(value) for value in vector]
                    if len(normalized) != self._profile.dimension:
                        raise RuntimeError(
                            f"BGE-M3 returned {len(normalized)} dimensions; expected 1024"
                        )
                    encoded[text] = normalized
                LOGGER.info(
                    "Embedding batch completed model=%s device=%s dtype=%s texts=%d "
                    "elapsed_ms=%.3f chunks_per_second=%.2f batch_degraded=%s",
                    self._profile.model_name,
                    self._device,
                    self._dtype,
                    len(batch),
                    elapsed * 1000,
                    len(batch) / max(elapsed, 1e-9),
                    selected_batch_size < self._batch_size,
                )
                offset += len(batch)
        return [encoded[unique[index]] for index in positions]


class ResilientEmbedding(EmbeddingClient):
    """Cache single-text calls and switch to Hash after provider failures/thresholds."""

    def __init__(
        self,
        primary: EmbeddingClient,
        *,
        fallback: EmbeddingClient | None,
        query_timeout_ms: int = 300,
        batch_timeout_seconds: float = 30,
        cache_ttl_seconds: float = 60,
        cache_max_entries: int = 512,
    ) -> None:
        self._active = primary
        self._fallback = fallback
        self._query_timeout_ms = query_timeout_ms
        self._batch_timeout_seconds = batch_timeout_seconds
        self._cache_ttl_seconds = cache_ttl_seconds
        self._cache_max_entries = cache_max_entries
        self._cache: OrderedDict[tuple[str, str], tuple[float, list[float]]] = OrderedDict()
        self._state_lock = threading.Lock()

    @property
    def profile(self) -> EmbeddingProfile | None:
        return self._active.profile

    async def embed(self, text: str) -> list[float]:
        key = ((self.profile.fingerprint if self.profile else "unknown"), text.strip())
        cached = self._cache_get(key)
        if cached is not None:
            return cached
        started = time.perf_counter()
        try:
            vector = await self._active.embed(text)
        except Exception as exc:
            vector = await self._fallback_single(text, exc)
        elapsed_ms = (time.perf_counter() - started) * 1000
        if elapsed_ms > self._query_timeout_ms and self._degrade_for_threshold(
            "query", elapsed_ms, self._query_timeout_ms
        ):
            vector = await self._active.embed(text)
        profile = self.profile
        cache_key = ((profile.fingerprint if profile else "unknown"), text.strip())
        self._cache_put(cache_key, vector)
        LOGGER.info(
            "Query embedding latency provider=%s model=%s elapsed_ms=%.3f",
            profile.provider if profile else "unknown",
            profile.model_name if profile else "unknown",
            elapsed_ms,
        )
        return vector

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        started = time.perf_counter()
        try:
            vectors = await self._active.embed_batch(texts)
        except Exception as exc:
            vectors = await self._fallback_batch(texts, exc)
        elapsed = time.perf_counter() - started
        if elapsed > self._batch_timeout_seconds and self._degrade_for_threshold(
                "batch", elapsed, self._batch_timeout_seconds
        ):
            vectors = await self._active.embed_batch(texts)
        return vectors

    async def _fallback_single(self, text: str, exc: Exception) -> list[float]:
        fallback = self._activate_fallback(exc)
        return await fallback.embed(text)

    async def _fallback_batch(
        self, texts: list[str], exc: Exception
    ) -> list[list[float]]:
        fallback = self._activate_fallback(exc)
        return await fallback.embed_batch(texts)

    def _activate_fallback(self, exc: Exception) -> EmbeddingClient:
        if self._fallback is None:
            raise EmbeddingUnavailableError("Embedding provider failed") from exc
        with self._state_lock:
            if self._active is not self._fallback:
                LOGGER.warning(
                    "Embedding provider degraded from=%s to=%s reason=%s",
                    _provider_name(self._active),
                    _provider_name(self._fallback),
                    type(exc).__name__,
                    exc_info=exc,
                )
                self._active = self._fallback
                self._cache.clear()
        return self._active

    def _degrade_for_threshold(
        self, operation: str, observed: float, threshold: float
    ) -> bool:
        if self._fallback is None or self._active is self._fallback:
            return False
        LOGGER.warning(
            "Embedding performance threshold exceeded operation=%s observed=%s "
            "threshold=%s; subsequent calls use fallback",
            operation,
            observed,
            threshold,
        )
        self._activate_fallback(TimeoutError(f"{operation} threshold exceeded"))
        return True

    def _cache_get(self, key: tuple[str, str]) -> list[float] | None:
        item = self._cache.get(key)
        if item is None:
            return None
        created_at, vector = item
        if time.monotonic() - created_at > self._cache_ttl_seconds:
            self._cache.pop(key, None)
            return None
        self._cache.move_to_end(key)
        return list(vector)

    def _cache_put(self, key: tuple[str, str], vector: list[float]) -> None:
        self._cache[key] = (time.monotonic(), list(vector))
        self._cache.move_to_end(key)
        while len(self._cache) > self._cache_max_entries:
            self._cache.popitem(last=False)


class UnavailableEmbedding(EmbeddingClient):
    def __init__(self, reason: Exception) -> None:
        self._reason = reason

    async def embed(self, text: str) -> list[float]:
        raise EmbeddingUnavailableError("Embedding provider is unavailable") from self._reason

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        raise EmbeddingUnavailableError("Embedding provider is unavailable") from self._reason


def build_embedding_client(settings: Any) -> EmbeddingClient:
    """Build one lifecycle-level provider without letting model load kill the Worker."""
    from backend.rag.local_models import HashEmbedding

    provider = str(settings.embedding_provider).strip().casefold()
    if provider not in {"hash", "bge_m3", "auto"}:
        raise ValueError(f"Unsupported EMBEDDING_PROVIDER: {provider}")
    fallback = HashEmbedding() if settings.embedding_fallback_enabled else None
    if provider == "hash":
        return ResilientEmbedding(
            HashEmbedding(),
            fallback=None,
            query_timeout_ms=settings.embedding_query_timeout_ms,
            batch_timeout_seconds=settings.embedding_batch_timeout_seconds,
            cache_ttl_seconds=settings.embedding_query_cache_ttl_seconds,
            cache_max_entries=settings.embedding_query_cache_max_entries,
        )
    try:
        primary: EmbeddingClient = BGEM3Embedding(
            model_name=settings.embedding_model_name,
            model_version=settings.embedding_model_version,
            device=settings.embedding_device,
            batch_size=settings.embedding_batch_size,
            max_length=settings.embedding_max_length,
            use_fp16=settings.embedding_use_fp16,
        )
    except Exception as exc:
        LOGGER.warning(
            "BGE-M3 failed to load; Worker continues with configured fallback",
            exc_info=exc,
        )
        if fallback is None:
            return UnavailableEmbedding(exc)
        primary = fallback
    return ResilientEmbedding(
        primary,
        fallback=fallback,
        query_timeout_ms=settings.embedding_query_timeout_ms,
        batch_timeout_seconds=settings.embedding_batch_timeout_seconds,
        cache_ttl_seconds=settings.embedding_query_cache_ttl_seconds,
        cache_max_entries=settings.embedding_query_cache_max_entries,
    )


def require_embedding_profile(client: EmbeddingClient) -> EmbeddingProfile:
    profile = getattr(client, "profile", None)
    if not isinstance(profile, EmbeddingProfile):
        raise ValueError("A versioned EmbeddingProfile is required for production indexing")
    return profile


def _prepare_unique(texts: Sequence[str]) -> tuple[list[str], list[int]]:
    unique: list[str] = []
    by_text: dict[str, int] = {}
    positions: list[int] = []
    for value in texts:
        text = value.strip()
        index = by_text.get(text)
        if index is None:
            index = len(unique)
            unique.append(text)
            by_text[text] = index
        positions.append(index)
    return unique, positions


def _resolve_device(torch: Any, configured: str) -> str:
    selected = configured.strip().casefold()
    if selected == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"
    if selected == "cuda" and not torch.cuda.is_available():
        raise EmbeddingUnavailableError("CUDA was requested but is unavailable")
    if selected not in {"cpu", "cuda"}:
        raise ValueError(f"Unsupported embedding device: {configured}")
    return selected


def _import_torch() -> Any:
    try:
        import torch  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - optional production dependency
        raise EmbeddingUnavailableError("torch is required for BGE-M3") from exc
    return torch


def _resolved_model_version(model: Any, configured: str) -> str:
    first = getattr(model, "_first_module", lambda: None)()
    auto_model = getattr(first, "auto_model", None)
    config = getattr(auto_model, "config", None)
    return str(getattr(config, "_commit_hash", None) or configured)


def _is_out_of_memory(torch: Any, exc: Exception) -> bool:
    oom_type = getattr(torch, "OutOfMemoryError", None)
    cuda_oom_type = getattr(getattr(torch, "cuda", None), "OutOfMemoryError", None)
    types = tuple(value for value in (oom_type, cuda_oom_type) if isinstance(value, type))
    return (bool(types) and isinstance(exc, types)) or "out of memory" in str(exc).casefold()


def _empty_cuda_cache(torch: Any, device: str) -> None:
    if device == "cuda" and torch.cuda.is_available():
        torch.cuda.empty_cache()


def _provider_name(client: EmbeddingClient) -> str:
    profile = getattr(client, "profile", None)
    return profile.provider if profile is not None else type(client).__name__


def normalized_hash_vector(values: list[float]) -> list[float]:
    """Normalize a dense vector; retained here for provider-level tests."""
    norm = math.sqrt(sum(value * value for value in values))
    return values if norm == 0 else [value / norm for value in values]
