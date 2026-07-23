"""Dependency-free multilingual retrieval models for local production use."""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter

from backend.core.ports.llm_client import EmbeddingClient, RerankerClient


def retrieval_terms(value: str) -> list[str]:
    lower = value.casefold()
    latin = re.findall(r"[a-z0-9]+(?:[_.-][a-z0-9]+)*", lower)
    cjk_runs = re.findall(r"[\u4e00-\u9fff]+", lower)
    cjk: list[str] = []
    for run in cjk_runs:
        cjk.extend(run)
        cjk.extend(run[index : index + 2] for index in range(len(run) - 1))
    return [*latin, *cjk]


class MultilingualHashEmbeddingClient(EmbeddingClient):
    """Stable hashing-vector baseline that handles Chinese and English terms."""

    def __init__(self, dimension: int = 1024) -> None:
        self._dimension = dimension

    async def embed(self, text: str) -> list[float]:
        vector = [0.0] * self._dimension
        counts = Counter(retrieval_terms(text))
        for term, count in counts.items():
            digest = hashlib.blake2b(term.encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(digest, "big") % self._dimension
            sign = 1.0 if digest[0] % 2 == 0 else -1.0
            vector[index] += sign * (1.0 + math.log(count))
        norm = math.sqrt(sum(value * value for value in vector))
        return vector if norm == 0 else [value / norm for value in vector]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [await self.embed(text) for text in texts]


class MultilingualLexicalReranker(RerankerClient):
    async def rerank(
        self, query: str, documents: list[str], top_k: int = 5
    ) -> list[tuple[int, float]]:
        query_counts = Counter(retrieval_terms(query))
        scored = []
        for index, document in enumerate(documents):
            document_counts = Counter(retrieval_terms(document))
            overlap = sum(
                min(count, document_counts.get(term, 0))
                for term, count in query_counts.items()
            )
            coverage = overlap / max(1, sum(query_counts.values()))
            phrase_bonus = 0.25 if query.casefold() in document.casefold() else 0.0
            scored.append((index, coverage + phrase_bonus))
        return sorted(scored, key=lambda item: (-item[1], item[0]))[:top_k]
