"""
Fake LLM, Embedding and Reranker clients
"""

from typing import Optional

from core.ports.llm_client import EmbeddingClient, LLMClient, RerankerClient


class FakeLLMClient(LLMClient):
    def __init__(self, should_fail: bool = False):
        self.should_fail = should_fail
        self.call_count = 0

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        top_p: float = 0.95,
        stop_sequences: Optional[list[str]] = None,
    ) -> str:
        self.call_count += 1
        if self.should_fail:
            raise RuntimeError("Simulated LLM failure")
        return f"Fake response to: {prompt[:50]}..."

    async def generate_with_schema(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        response_schema: Optional[dict] = None,
        max_tokens: int = 2048,
        temperature: float = 0.7,
    ) -> str:
        self.call_count += 1
        if self.should_fail:
            raise RuntimeError("Simulated LLM failure")
        return '{"response": "fake structured response"}'


class FakeEmbeddingClient(EmbeddingClient):
    def __init__(self, should_fail: bool = False):
        self.should_fail = should_fail

    async def embed(self, text: str) -> list[float]:
        if self.should_fail:
            raise RuntimeError("Simulated embedding failure")
        # Return a fake embedding (e.g., hash-based)
        return [float(ord(c)) for c in text[:10]]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if self.should_fail:
            raise RuntimeError("Simulated embedding failure")
        return [await self.embed(text) for text in texts]


class FakeRerankerClient(RerankerClient):
    def __init__(self, should_fail: bool = False):
        self.should_fail = should_fail

    async def rerank(
        self, query: str, documents: list[str], top_k: int = 5
    ) -> list[tuple[int, float]]:
        if self.should_fail:
            raise RuntimeError("Simulated reranking failure")
        # Return fake reranking results
        return [(i, 1.0 - (i * 0.1)) for i in range(min(top_k, len(documents)))]
