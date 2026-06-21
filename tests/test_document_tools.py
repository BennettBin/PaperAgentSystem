from io import BytesIO

import fitz
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from document_processing.pipeline import BasicPDFPipeline
from infrastructure.fake.adapters import FakeObjectStore
from infrastructure.fake.observability import FakeTraceWriter
from infrastructure.postgres.models import Base
from rag.indexing import DocumentIndexer
from rag.retrieval import HybridRetriever
from tool_runtime import (
    InMemoryDataRefStore,
    InMemoryIdempotencyStore,
    ToolContext,
    ToolRegistry,
    ToolRuntime,
)
from tool_runtime.document_tools import register_document_tools
from workspace.service import WorkspaceService


def pdf() -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((50, 60), "1 Results", fontsize=16)
    page.insert_text((50, 100), "Calibration accuracy reached 95%.", fontsize=11)
    stream = BytesIO()
    document.save(stream)
    document.close()
    return stream.getvalue()


def vector(text: str) -> list[float]:
    return [1.0 if "calibration" in text.lower() else 0.0]


class Embeddings:
    async def embed(self, text: str) -> list[float]:
        return vector(text)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [vector(text) for text in texts]


class Reranker:
    async def rerank(self, query: str, documents: list[str], top_k: int = 5):
        return [(index, 1.0) for index in range(min(top_k, len(documents)))]


@pytest.mark.asyncio
async def test_parse_search_and_section_tools_integrate(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'document-tools.db').as_posix()}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    workspace = WorkspaceService(tmp_path / "mount", sessions, FakeObjectStore())
    entry = await workspace.write_entry(
        "ws-1",
        "conv-1",
        "inputs/paper.pdf",
        pdf(),
        "application/pdf",
        task_id="task-1",
    )
    embeddings = Embeddings()
    indexer = DocumentIndexer(sessions, embeddings, embedding_model="fixture")
    retriever = HybridRetriever(sessions, embeddings, Reranker())
    registry = ToolRegistry()
    register_document_tools(
        registry,
        workspace,
        BasicPDFPipeline(),
        indexer,
        retriever,
        sessions,
    )
    runtime = ToolRuntime(
        registry,
        idempotency_store=InMemoryIdempotencyStore(),
        data_ref_store=InMemoryDataRefStore(),
        trace_writer=FakeTraceWriter(),
        max_inline_bytes=100_000,
    )
    context = ToolContext(
        workspace_id="ws-1",
        user_id="user-1",
        conversation_id="conv-1",
        task_id="task-1",
        trace_id="trace-1",
        permissions=frozenset({"workspace:read"}),
        allowed_tools=frozenset(
            {"parse_document", "search_document", "get_document_section"}
        ),
    )

    parsed = await runtime.invoke(
        "parse_document",
        {"workspace_entry_id": entry.entry_id},
        context,
        "parse-1",
    )
    searched = await runtime.invoke(
        "search_document",
        {"query": "calibration accuracy", "file_ids": [entry.entry_id]},
        context,
        "search-1",
    )
    section = await runtime.invoke(
        "get_document_section",
        {"file_id": entry.entry_id, "section_title": "Results"},
        context,
        "section-1",
    )

    assert parsed.output["quality_score"] >= 0.6
    assert searched.output["hits"][0]["page_start"] == 1
    assert "95%" in section.output["chunks"][0]["text"]
