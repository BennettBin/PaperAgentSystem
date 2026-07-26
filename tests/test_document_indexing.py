from io import BytesIO

import fitz
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.document_processing.pdf_parser import PyMuPDFParser
from backend.infrastructure.postgres.models import (
    Base,
    DocumentChunkModel,
    DocumentSectionModel,
    ParsedDocumentModel,
)
from backend.rag.indexing import CURRENT_INDEX_VERSION, DocumentIndexer, StructureAwareChunker
from backend.rag.local_models import HashEmbedding


def paper_pdf() -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((50, 60), "1 Introduction", fontsize=16)
    for index in range(12):
        page.insert_text(
            (50, 100 + index * 25),
            f"Sentence {index} contains traceable evidence token{index}.",
            fontsize=11,
        )
    stream = BytesIO()
    document.save(stream)
    document.close()
    return stream.getvalue()


class CountingEmbeddings:
    def __init__(self) -> None:
        self.calls = 0

    async def embed(self, text: str) -> list[float]:
        self.calls += 1
        return [float(len(text))]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        self.calls += len(texts)
        return [[float(len(text))] for text in texts]


@pytest.fixture
def database(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'chunks.db').as_posix()}")
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)


@pytest.mark.asyncio
async def test_parent_child_chunks_are_fully_traceable(database) -> None:
    data = paper_pdf()
    parsed = await PyMuPDFParser().parse(data, "paper.pdf")
    embeddings = CountingEmbeddings()
    indexer = DocumentIndexer(
        database,
        embeddings,
        embedding_model="fake-v1",
        chunker=StructureAwareChunker(child_character_limit=140),
    )

    chunks = await indexer.index("ws-1", "file-1", data, parsed)

    parents = [chunk for chunk in chunks if chunk.level == "parent"]
    children = [chunk for chunk in chunks if chunk.level == "child"]
    assert parents and len(children) > 1
    assert all(chunk.parent_chunk_id for chunk in children)
    assert all(chunk.section_path == ["1 Introduction"] for chunk in chunks)
    assert all(chunk.source_block_ids for chunk in chunks)
    assert all(chunk.page_start == chunk.page_end == 1 for chunk in chunks)
    source_ids = {
        block.block_id
        for page in parsed.pages
        for block in page.blocks
        if block.role == "body"
    }
    assert all(set(chunk.source_block_ids) <= source_ids for chunk in chunks)
    assert children[0].next_chunk_id == children[1].chunk_id
    assert children[1].previous_chunk_id == children[0].chunk_id
    assert all(chunk.section_id == parsed.sections[0].section_id for chunk in chunks)
    assert all(chunk.section_number == "1" for chunk in chunks)
    assert [chunk.chunk_index_in_section for chunk in children] == list(
        range(len(children))
    )
    with database() as session:
        catalog = session.query(DocumentSectionModel).all()
        stored_chunks = session.query(DocumentChunkModel).all()
        assert len(catalog) == len(parsed.sections)
        assert catalog[0].heading_block_id == parsed.sections[0].heading_block_id
        assert all(model.section_id for model in stored_chunks)


@pytest.mark.asyncio
async def test_duplicate_content_does_not_repeat_embeddings(database) -> None:
    data = paper_pdf()
    parsed = await PyMuPDFParser().parse(data, "paper.pdf")
    embeddings = CountingEmbeddings()
    indexer = DocumentIndexer(database, embeddings, embedding_model="fake-v1")

    first = await indexer.index("ws-1", "file-1", data, parsed)
    calls = embeddings.calls
    second = await indexer.index("ws-1", "file-1", data, parsed)

    assert second
    assert len(second) == len(first)
    assert embeddings.calls == calls
    assert all(len(chunk.embedding) == 1024 for chunk in second)


@pytest.mark.asyncio
async def test_workspace_isolation_and_delete_invalidation(database) -> None:
    data = paper_pdf()
    parsed = await PyMuPDFParser().parse(data, "paper.pdf")
    embeddings = CountingEmbeddings()
    indexer = DocumentIndexer(database, embeddings, embedding_model="fake-v1")

    first = await indexer.index("ws-1", "file-1", data, parsed)
    second = await indexer.index("ws-2", "file-1", data, parsed)
    indexer.delete("ws-1", "file-1")
    reindexed = await indexer.index("ws-1", "file-1", data, parsed)

    assert {chunk.workspace_id for chunk in second} == {"ws-2"}
    assert reindexed[0].document_id != first[0].document_id
    with database() as session:
        assert (
            session.query(DocumentSectionModel)
            .filter(DocumentSectionModel.workspace_id == "ws-1")
            .count()
            == len(parsed.sections)
        )


@pytest.mark.asyncio
async def test_old_index_version_is_detected_and_rebuilt(database) -> None:
    data = paper_pdf()
    parsed = await PyMuPDFParser().parse(data, "paper.pdf")
    embeddings = CountingEmbeddings()
    indexer = DocumentIndexer(database, embeddings, embedding_model="fake-v1")
    first = await indexer.index("ws-1", "file-1", data, parsed)
    calls_after_first = embeddings.calls
    with database() as session:
        stored = session.query(ParsedDocumentModel).one()
        stored.metadata_json = {
            **(stored.metadata_json or {}),
            "index_version": CURRENT_INDEX_VERSION - 1,
        }
        session.commit()

    assert indexer.is_current("ws-1", "file-1") is False
    rebuilt = await indexer.index("ws-1", "file-1", data, parsed)

    assert rebuilt[0].document_id != first[0].document_id
    assert embeddings.calls > calls_after_first
    assert indexer.is_current("ws-1", "file-1") is True
    with database() as session:
        stored = session.query(ParsedDocumentModel).one()
        assert stored.metadata_json["index_version"] == CURRENT_INDEX_VERSION


@pytest.mark.asyncio
async def test_versioned_embedding_profile_is_persisted(database) -> None:
    data = paper_pdf()
    parsed = await PyMuPDFParser().parse(data, "paper.pdf")
    embeddings = HashEmbedding()
    indexer = DocumentIndexer(database, embeddings)

    chunks = await indexer.index("ws-1", "file-1", data, parsed)

    assert chunks
    assert indexer.is_current("ws-1", "file-1") is True
    with database() as session:
        stored = session.query(DocumentChunkModel).first()
        assert stored.embedding_provider == "hash"
        assert stored.embedding_fingerprint == embeddings.profile.fingerprint
        assert stored.embedding_status == "ready"
