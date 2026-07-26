"""Compare Hash and BGE-M3 Top-K while retaining exact and BM25 channels."""

from __future__ import annotations

import argparse
import asyncio
import json

from backend.infrastructure.config import InfrastructureSettings
from backend.infrastructure.postgres.models import DocumentChunkModel
from backend.rag.embeddings import build_embedding_client
from backend.rag.retrieval import BM25Retriever, ExactMatchRetriever, ResultMerger, VectorRetriever

DOCUMENTS = {
    "identical": "BGE-M3 supports dense multilingual retrieval.",
    "keywords": "Transformer retrieval uses BGE-M3 embeddings and BM25 reranking.",
    "zh_semantic": "该方法可以降低大语言模型生成错误事实的概率。",
    "en_semantic": "The approach reduces fabricated facts produced by language models.",
    "cross_language": "Graph neural networks improve molecular property prediction.",
    "technical": "The Llama-3.1-8B model reaches 92.5% accuracy with 7 billion parameters.",
    "distractor_a": "Database transactions provide atomicity and isolation.",
    "distractor_b": "Image segmentation is evaluated with the Dice coefficient.",
}

CASES = (
    ("完全相同文本", DOCUMENTS["identical"], "identical"),
    ("关键词高度重合", "Transformer BGE-M3 BM25 retrieval", "keywords"),
    ("中文同义改写", "这个方案能减少模型胡编乱造的内容吗？", "zh_semantic"),
    ("英文同义改写", "Does the method mitigate hallucinated statements?", "en_semantic"),
    ("中文查询英文论文", "图神经网络如何用于分子性质预测？", "cross_language"),
    ("术语数字模型名称", "Llama-3.1-8B 的 92.5% 和参数量", "technical"),
)


async def evaluate(provider: str, device: str, top_k: int) -> list[dict[str, object]]:
    settings = InfrastructureSettings().model_copy(
        update={
            "embedding_provider": provider,
            "embedding_device": device,
            "embedding_fallback_enabled": False,
            "embedding_query_timeout_ms": 10**9,
            "embedding_batch_timeout_seconds": 10**9,
        }
    )
    embeddings = build_embedding_client(settings)
    ids = list(DOCUMENTS)
    vectors = await embeddings.embed_batch([DOCUMENTS[key] for key in ids])
    models = [
        DocumentChunkModel(
            id=key,
            workspace_id="evaluation",
            file_id=key,
            document_id=key,
            parent_chunk_id=None,
            level="child",
            section_path=["Evaluation"],
            text=DOCUMENTS[key],
            page_start=1,
            page_end=1,
            bbox_json=[0, 0, 1, 1],
            source_block_ids=[key],
            embedding=vector,
            embedding_model=provider,
            searchable_text=DOCUMENTS[key],
        )
        for key, vector in zip(ids, vectors)
    ]
    exact = ExactMatchRetriever()
    bm25 = BM25Retriever()
    dense = VectorRetriever()
    merger = ResultMerger(60)
    output: list[dict[str, object]] = []
    for name, query, expected in CASES:
        query_vector = await embeddings.embed(query)
        scores = merger.merge(
            [
                exact.retrieve(query, models, len(models)),
                bm25.retrieve(query, models, len(models)),
                dense.retrieve(query_vector, models, len(models)),
            ]
        )
        ranking = sorted(scores, key=lambda key: (-scores[key], key))[:top_k]
        output.append(
            {
                "case": name,
                "query": query,
                "expected": expected,
                "top_k": ranking,
                "expected_rank": (
                    ranking.index(expected) + 1 if expected in ranking else None
                ),
            }
        )
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--providers", default="hash,bge_m3")
    parser.add_argument("--device", default="auto")
    parser.add_argument("--top-k", type=int, default=3)
    args = parser.parse_args()
    payload = {
        provider: asyncio.run(evaluate(provider, args.device, args.top_k))
        for provider in args.providers.split(",")
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
