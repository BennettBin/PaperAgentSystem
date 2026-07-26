from contextlib import nullcontext

import pytest

from backend.core.ports.llm_client import EmbeddingClient, EmbeddingProfile
from backend.rag.embeddings import BGEM3Embedding, ResilientEmbedding
from backend.rag.local_models import HashEmbedding


class FakeCuda:
    class OutOfMemoryError(RuntimeError):
        pass

    @staticmethod
    def is_available() -> bool:
        return True

    @staticmethod
    def empty_cache() -> None:
        return None


class FakeTorch:
    float16 = "float16"
    cuda = FakeCuda()
    OutOfMemoryError = FakeCuda.OutOfMemoryError

    @staticmethod
    def inference_mode():
        return nullcontext()


class FakeModel:
    def __init__(self, *, fail_above: int | None = None) -> None:
        self.fail_above = fail_above
        self.calls: list[list[str]] = []
        self.max_seq_length = 0
        self.eval_called = False

    def eval(self) -> None:
        self.eval_called = True

    def encode(self, texts, **_kwargs):
        values = list(texts)
        self.calls.append(values)
        if self.fail_above is not None and len(values) > self.fail_above:
            raise FakeCuda.OutOfMemoryError("CUDA out of memory")
        return [[float(len(text))] + [0.0] * 1023 for text in values]


@pytest.mark.asyncio
async def test_bge_batch_deduplicates_empty_text_and_caps_model_length() -> None:
    model = FakeModel()
    embeddings = BGEM3Embedding(
        model=model,
        torch_module=FakeTorch(),
        device="cuda",
        batch_size=32,
        max_length=512,
    )

    vectors = await embeddings.embed_batch(["same", " ", "same", "different"])

    assert model.eval_called is True
    assert model.max_seq_length == 512
    assert model.calls == [["same", "different"]]
    assert vectors[0] == vectors[2]
    assert vectors[1] == [0.0] * 1024
    assert embeddings.profile.dimension == 1024


@pytest.mark.asyncio
async def test_bge_retries_oom_with_smaller_batch() -> None:
    model = FakeModel(fail_above=2)
    embeddings = BGEM3Embedding(
        model=model,
        torch_module=FakeTorch(),
        device="cuda",
        batch_size=4,
    )

    vectors = await embeddings.embed_batch(["a", "b", "c", "d"])

    assert len(vectors) == 4
    assert [len(call) for call in model.calls] == [4, 2, 2]


class CountingEmbedding(EmbeddingClient):
    def __init__(self, profile: EmbeddingProfile, *, fail: bool = False) -> None:
        self._profile = profile
        self.fail = fail
        self.calls = 0

    @property
    def profile(self) -> EmbeddingProfile:
        return self._profile

    async def embed(self, text: str) -> list[float]:
        self.calls += 1
        if self.fail:
            raise RuntimeError("inference failed")
        return [1.0] + [0.0] * 1023

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if self.fail:
            raise RuntimeError("inference failed")
        return [await self.embed(text) for text in texts]


@pytest.mark.asyncio
async def test_query_cache_and_failure_switch_to_hash_profile() -> None:
    bge = CountingEmbedding(
        EmbeddingProfile("bge_m3", "BAAI/bge-m3", "revision", 1024, 512, True)
    )
    client = ResilientEmbedding(
        bge,
        fallback=HashEmbedding(),
        query_timeout_ms=10_000,
        batch_timeout_seconds=10_000,
    )

    first = await client.embed("cached query")
    second = await client.embed("cached query")
    bge.fail = True
    fallback = await client.embed("new query")

    assert first == second
    assert bge.calls == 2
    assert len(fallback) == 1024
    assert client.profile is not None
    assert client.profile.provider == "hash"


@pytest.mark.asyncio
async def test_threshold_fallback_recomputes_vector_in_fallback_space() -> None:
    bge = CountingEmbedding(
        EmbeddingProfile("bge_m3", "BAAI/bge-m3", "revision", 1024, 512, True)
    )
    hash_embeddings = HashEmbedding()
    client = ResilientEmbedding(
        bge,
        fallback=hash_embeddings,
        query_timeout_ms=-1,
        batch_timeout_seconds=10_000,
    )

    vector = await client.embed("semantic query")

    assert client.profile is not None
    assert client.profile.provider == "hash"
    assert vector == await hash_embeddings.embed("semantic query")
