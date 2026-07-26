import hashlib

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.core.ports.llm_client import EmbeddingProfile
from backend.infrastructure.postgres.models import (
    Base,
    DocumentChunkModel,
    DocumentSectionModel,
    ParsedDocumentModel,
)
from backend.rag.local_models import (
    MultilingualHashEmbeddingClient,
    MultilingualLexicalReranker,
)
from backend.rag.retrieval import HybridRetriever

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


class VersionedTopicEmbeddings(TopicEmbeddings):
    @property
    def profile(self) -> EmbeddingProfile:
        return EmbeddingProfile("fixture", "topics", "v1", 1024, 512, True)


class RecordingVectorRetriever:
    def __init__(self) -> None:
        self.chunk_ids: list[str] = []

    def retrieve(self, query, chunks, limit):
        self.chunk_ids = [chunk.id for chunk in chunks]
        return []


class LexicalReranker:
    async def rerank(self, query: str, documents: list[str], top_k: int = 5):
        terms = set(query.lower().split())
        scored = [
            (index, len(terms & set(document.lower().split())))
            for index, document in enumerate(documents)
        ]
        return sorted(scored, key=lambda item: (-item[1], item[0]))[:top_k]


class ZeroEmbeddings:
    async def embed(self, text: str) -> list[float]:
        return [0.0] * 1024

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * 1024 for _ in texts]


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

    pass_at_5 = sum(rank is not None and rank <= 5 for rank in ranks) / len(ranks)
    recall_at_10 = sum(rank is not None and rank <= 10 for rank in ranks) / len(ranks)
    mrr_at_10 = sum(1 / rank if rank is not None and rank <= 10 else 0 for rank in ranks) / len(ranks)
    assert pass_at_5 >= 0.90
    assert recall_at_10 >= 0.95
    assert mrr_at_10 >= 0.80


@pytest.mark.asyncio
async def test_named_section_expands_contiguous_section_context(database) -> None:
    retriever = HybridRetriever(database, TopicEmbeddings(), LexicalReranker())

    hits = await retriever.search(
        "bayesian calibration",
        workspace_id="ws-1",
        file_ids={"file-0"},
        section_hint="Results",
        expand_section=True,
        limit=5,
    )

    assert len(hits) >= 3
    assert all(hit.section_path == ("Results",) for hit in hits[:3])


@pytest.mark.asyncio
async def test_exact_and_bm25_recall_work_when_vectors_are_uninformative(database) -> None:
    retriever = HybridRetriever(database, ZeroEmbeddings(), LexicalReranker())

    hits = await retriever.search("unique token topic6", workspace_id="ws-1", limit=5)

    assert hits
    assert hits[0].file_id == "file-6"


@pytest.mark.asyncio
async def test_vector_channel_only_receives_matching_embedding_profile(database) -> None:
    embeddings = VersionedTopicEmbeddings()
    with database() as session:
        compatible = session.get(DocumentChunkModel, "ws-1-0-0")
        assert compatible is not None
        compatible.embedding_fingerprint = embeddings.profile.fingerprint
        compatible.embedding_status = "ready"
        incompatible = session.get(DocumentChunkModel, "ws-1-0-1")
        assert incompatible is not None
        incompatible.embedding_fingerprint = "hash:other@v1:d1024:l0:n1"
        incompatible.embedding_status = "ready"
        session.commit()
    retriever = HybridRetriever(database, embeddings, LexicalReranker())
    recorder = RecordingVectorRetriever()
    retriever._vectors = recorder

    await retriever.search(
        "bayesian calibration", workspace_id="ws-1", file_ids={"file-0"}
    )

    assert recorder.chunk_ids == ["ws-1-0-0"]


@pytest.mark.asyncio
async def test_production_local_retrieval_pass_at_5(database) -> None:
    embeddings = MultilingualHashEmbeddingClient()
    with database() as session:
        models = session.query(DocumentChunkModel).all()
        for model in models:
            model.embedding = await embeddings.embed(model.searchable_text)
        session.commit()
    retriever = HybridRetriever(
        database,
        embeddings,
        MultilingualLexicalReranker(),
    )
    queries = [
        (f"{topic} benchmark topic{index}", f"file-{index}")
        for index, topic in enumerate(TOPICS)
    ] + [
        ("retrieval augmented generation 的实验结果", "file-8"),
        ("medical segmentation 方法", "file-7"),
        ("causal inference benchmark", "file-2"),
        ("federated privacy evidence", "file-5"),
        ("quantum optimization result", "file-9"),
    ]
    ranks = []
    for query, expected_file in queries:
        hits = await retriever.search(query, workspace_id="ws-1", limit=10)
        ranks.append(
            next(
                (
                    position
                    for position, hit in enumerate(hits, start=1)
                    if hit.file_id == expected_file
                ),
                None,
            )
        )

    pass_at_5 = sum(rank is not None and rank <= 5 for rank in ranks) / len(ranks)
    recall_at_10 = sum(rank is not None and rank <= 10 for rank in ranks) / len(ranks)
    mrr_at_10 = sum(
        1 / rank if rank is not None and rank <= 10 else 0 for rank in ranks
    ) / len(ranks)
    assert pass_at_5 >= 0.90
    assert recall_at_10 >= 0.95
    assert mrr_at_10 >= 0.80


@pytest.fixture
def section_database(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'section-retrieval.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as session:
        session.add(
            ParsedDocumentModel(
                id="doc-sections",
                workspace_id="ws-1",
                file_id="paper-1",
                checksum="a" * 64,
                parser_name="fixture",
                parser_version="1",
                page_count=8,
                quality_score=100,
            )
        )
        sections = [
            ("s4", "4", "Experiments", None, 0),
            ("s41", "4.1", "Datasets", "s4", 1),
            ("s42", "4.2", "Ablation Study", "s4", 2),
            ("s5", "5", "Conclusion", None, 3),
        ]
        for section_id, number, title, parent_id, ordinal in sections:
            session.add(
                DocumentSectionModel(
                    id=f"row-{section_id}",
                    workspace_id="ws-1",
                    file_id="paper-1",
                    document_id="doc-sections",
                    section_id=section_id,
                    number=number,
                    title=title,
                    normalized_title=title.casefold(),
                    level=1 if parent_id is None else 2,
                    parent_section_id=parent_id,
                    section_path=(
                        ["4 Experiments", f"{number} {title}"]
                        if parent_id
                        else [f"{number} {title}"]
                    ),
                    ordinal=ordinal,
                    page_start=ordinal + 1,
                    page_end=ordinal + 1,
                    heading_block_id=f"heading-{section_id}",
                )
            )
        chunk_specs = [
            ("c4", "s4", "Experiments", ["4 Experiments"], 0, "Experiment overview and protocol."),
            ("c41", "s41", "Datasets", ["4 Experiments", "4.1 Datasets"], 0, "The study uses PaperBench and ScholarQA datasets."),
            ("c42", "s42", "Ablation Study", ["4 Experiments", "4.2 Ablation Study"], 0, "The ablation removes memory, routing, and reranking."),
            ("c5", "s5", "Conclusion", ["5 Conclusion"], 0, "The conclusion describes future work."),
        ]
        for index, (chunk_id, section_id, title, path, chunk_index, text) in enumerate(chunk_specs):
            session.add(
                DocumentChunkModel(
                    id=chunk_id,
                    workspace_id="ws-1",
                    file_id="paper-1",
                    document_id="doc-sections",
                    parent_chunk_id=None,
                    level="child",
                    section_id=section_id,
                    section_number=path[-1].split()[0],
                    section_title=title,
                    section_path=path,
                    chunk_index_in_section=chunk_index,
                    text=text,
                    page_start=index + 1,
                    page_end=index + 1,
                    bbox_json=[0, 0, 100, 100],
                    source_block_ids=[f"block-{chunk_id}"],
                    embedding=vector(text),
                    embedding_model="topic-v1",
                    searchable_text=f"{' / '.join(path)}\n{text}",
                )
            )
        session.commit()
    return factory


@pytest.mark.asyncio
async def test_parent_section_summary_includes_descendants_in_document_order(
    section_database,
) -> None:
    retriever = HybridRetriever(
        section_database,
        TopicEmbeddings(),
        LexicalReranker(),
    )

    result = await retriever.search_section(
        "请总结第 4 节",
        workspace_id="ws-1",
        file_ids={"paper-1"},
        max_context_characters=10_000,
    )

    assert result.resolution.status == "resolved"
    assert result.mode == "summary"
    assert result.scope_section_ids == ("s4", "s41", "s42")
    assert [hit.chunk_id for hit in result.hits] == ["c4", "c41", "c42"]
    assert result.truncated is False


@pytest.mark.asyncio
async def test_section_qa_uses_exact_resolved_scope(section_database) -> None:
    retriever = HybridRetriever(
        section_database,
        TopicEmbeddings(),
        LexicalReranker(),
    )

    result = await retriever.search_section(
        "第 4.1 节使用了什么数据集？",
        workspace_id="ws-1",
        file_ids={"paper-1"},
    )

    assert result.resolution.status == "resolved"
    assert result.mode == "qa"
    assert result.scope_section_ids == ("s41",)
    assert result.hits
    assert {hit.chunk_id for hit in result.hits} == {"c41"}


@pytest.mark.asyncio
async def test_section_qa_expands_adjacent_chunks_after_rerank(
    section_database,
) -> None:
    with section_database() as session:
        for index, text in (
            (1, "Dataset preprocessing details before the metric."),
            (2, "The special metric reaches 97 percent accuracy."),
            (3, "Dataset limitations discussed after the metric."),
        ):
            session.add(
                DocumentChunkModel(
                    id=f"qa-adjacent-{index}",
                    workspace_id="ws-1",
                    file_id="paper-1",
                    document_id="doc-sections",
                    parent_chunk_id=None,
                    level="child",
                    section_id="s41",
                    section_number="4.1",
                    section_title="Datasets",
                    section_path=["4 Experiments", "4.1 Datasets"],
                    chunk_index_in_section=index,
                    text=text,
                    page_start=2,
                    page_end=2,
                    bbox_json=[0, 0, 100, 100],
                    source_block_ids=[f"qa-block-{index}"],
                    embedding=vector(text),
                    embedding_model="topic-v1",
                    searchable_text=text,
                )
            )
        session.commit()
    retriever = HybridRetriever(
        section_database,
        TopicEmbeddings(),
        LexicalReranker(),
    )

    result = await retriever.search_section(
        "第 4.1 节的 special metric 是多少？",
        workspace_id="ws-1",
        file_ids={"paper-1"},
        limit=3,
    )

    assert [hit.chunk_id for hit in result.hits] == [
        "qa-adjacent-1",
        "qa-adjacent-2",
        "qa-adjacent-3",
    ]


@pytest.mark.asyncio
async def test_long_section_summary_keeps_head_middle_tail_under_budget(
    section_database,
) -> None:
    with section_database() as session:
        for index in range(1, 6):
            text = f"ordered segment {index} " + ("x" * 60)
            session.add(
                DocumentChunkModel(
                    id=f"c41-{index}",
                    workspace_id="ws-1",
                    file_id="paper-1",
                    document_id="doc-sections",
                    parent_chunk_id=None,
                    level="child",
                    section_id="s41",
                    section_number="4.1",
                    section_title="Datasets",
                    section_path=["4 Experiments", "4.1 Datasets"],
                    chunk_index_in_section=index,
                    text=text,
                    page_start=index + 2,
                    page_end=index + 2,
                    bbox_json=[0, 0, 100, 100],
                    source_block_ids=[f"block-c41-{index}"],
                    embedding=vector(text),
                    embedding_model="topic-v1",
                    searchable_text=text,
                )
            )
        session.commit()
    retriever = HybridRetriever(
        section_database,
        TopicEmbeddings(),
        LexicalReranker(),
    )

    result = await retriever.search_section(
        "总结第 4.1 节",
        workspace_id="ws-1",
        file_ids={"paper-1"},
        max_context_characters=180,
    )

    ids = [hit.chunk_id for hit in result.hits]
    assert result.truncated is True
    assert ids[0] == "c41"
    assert "c41-3" in ids
    assert ids[-1] == "c41-5"


@pytest.mark.asyncio
async def test_duplicate_section_number_across_files_requires_clarification(
    section_database,
) -> None:
    with section_database() as session:
        session.add(
            ParsedDocumentModel(
                id="doc-other",
                workspace_id="ws-1",
                file_id="paper-2",
                checksum="b" * 64,
                parser_name="fixture",
                parser_version="1",
                page_count=1,
                quality_score=100,
            )
        )
        session.add(
            DocumentSectionModel(
                id="row-other-s4",
                workspace_id="ws-1",
                file_id="paper-2",
                document_id="doc-other",
                section_id="other-s4",
                number="4",
                title="Evaluation",
                normalized_title="evaluation",
                level=1,
                parent_section_id=None,
                section_path=["4 Evaluation"],
                ordinal=0,
                page_start=1,
                page_end=1,
                heading_block_id="other-heading",
            )
        )
        session.commit()
    retriever = HybridRetriever(
        section_database,
        TopicEmbeddings(),
        LexicalReranker(),
    )

    result = await retriever.search_section(
        "总结第 4 节",
        workspace_id="ws-1",
        file_ids={"paper-1", "paper-2"},
    )

    assert result.resolution.status == "ambiguous"
    assert result.resolution.clarification_question
    assert result.hits == ()
