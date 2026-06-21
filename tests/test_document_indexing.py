from io import BytesIO

import fitz
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from document_processing.pdf_parser import PyMuPDFParser
from infrastructure.postgres.models import Base
from rag.indexing import DocumentIndexer, StructureAwareChunker


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
