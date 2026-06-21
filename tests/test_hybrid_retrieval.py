import hashlib

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from infrastructure.postgres.models import Base, DocumentChunkModel, ParsedDocumentModel
from rag.retrieval import HybridRetriever

TOPICS = [
    "bayesian calibration",
    "graph neural networks",
    "causal inference",
    "protein folding",
    "reinforcement learning",
    "federated privacy",
    "climate forecasting",
    "medical segmentation",
    "retrieval augmented generation",
    "quantum optimization",
]


def vector(text: str) -> list[float]:
    values = [0.0] * len(TOPICS)
    lower = text.lower()
    for index, topic in enumerate(TOPICS):
        if topic in lower:
            values[index] = 1.0
    return values + [0.0] * (1024 - len(values))


class TopicEmbeddings:
    async def embed(self, text: str) -> list[float]:
        return vector(text)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [vector(text) for text in texts]


class LexicalReranker:
    async def rerank(self, query: str, documents: list[str], top_k: int = 5):
        terms = set(query.lower().split())
        scored = [
            (index, len(terms & set(document.lower().split())))
            for index, document in enumerate(documents)
        ]
        return sorted(scored, key=lambda item: (-item[1], item[0]))[:top_k]


@pytest.fixture
def database(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'retrieval.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as session:
        for workspace in ("ws-1", "ws-2"):
            for index, topic in enumerate(TOPICS):
                document_id = hashlib.sha1(f"{workspace}-{index}".encode()).hexdigest()
                session.add(
                    ParsedDocumentModel(
                        id=document_id,
                        workspace_id=workspace,
                        file_id=f"file-{index}",
                        checksum=document_id,
                        parser_name="fixture",
                        parser_version="1",
                        page_count=1,
                        quality_score=100,
                    )
                )
                for variant in range(3):
                    content = (
                        f"This evidence discusses {topic} benchmark variant {variant} "
                        f"with unique token topic{index}."
                    )
                    session.add(
                        DocumentChunkModel(
                            id=f"{workspace}-{index}-{variant}",
                            workspace_id=workspace,
                            file_id=f"file-{index}",
                            document_id=document_id,
                            parent_chunk_id=f"parent-{index}",
                            level="child",
                            section_path=["Results"],
                            text=content,
                            page_start=1,
                            page_end=1,
                            bbox_json=[0, 0, 100, 100],
                            source_block_ids=[f"block-{index}-{variant}"],
                            embedding=vector(content),
                            embedding_model="topic-v1",
                            searchable_text=content,
                        )
                    )
        session.commit()
    return factory


@pytest.mark.asyncio
async def test_hybrid_retrieval_filters_workspace_and_file(database) -> None:
    retriever = HybridRetriever(database, TopicEmbeddings(), LexicalReranker())

    hits = await retriever.search(
        "bayesian calibration",
        workspace_id="ws-1",
        file_ids={"file-0"},
    )

    assert hits
    assert {hit.workspace_id for hit in hits} == {"ws-1"}
    assert {hit.file_id for hit in hits} == {"file-0"}
    assert all(hit.source_block_ids and hit.page_start == 1 for hit in hits)


@pytest.mark.asyncio
async def test_retrieval_evaluation_thresholds(database) -> None:
    retriever = HybridRetriever(database, TopicEmbeddings(), LexicalReranker())
    ranks = []
    for repeat in range(10):
        for index, topic in enumerate(TOPICS):
            hits = await retriever.search(
                f"{topic} topic{index}",
                workspace_id="ws-1",
                limit=10,
            )
            expected_file = f"file-{index}"
            rank = next(
                (
                    position
                    for position, hit in enumerate(hits, start=1)
                    if hit.file_id == expected_file
                ),
                None,
            )
            ranks.append(rank)

    recall_at_5 = sum(rank is not None and rank <= 5 for rank in ranks) / len(ranks)
    recall_at_10 = sum(rank is not None and rank <= 10 for rank in ranks) / len(ranks)
    mrr_at_10 = sum(1 / rank if rank is not None and rank <= 10 else 0 for rank in ranks) / len(ranks)
    assert recall_at_5 >= 0.80
    assert recall_at_10 >= 0.90
    assert mrr_at_10 >= 0.75
