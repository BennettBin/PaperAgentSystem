"""Structure-aware parent/child chunking and idempotent indexing."""

from __future__ import annotations

import hashlib
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from core.ports.llm_client import EmbeddingClient
from document_processing.schema import BoundingBox, ParsedDocument, TextBlock
from infrastructure.postgres.models import DocumentChunkModel, ParsedDocumentModel
from rag.schema import DocumentChunk


class StructureAwareChunker:
    def __init__(self, child_character_limit: int = 700) -> None:
        self._limit = child_character_limit

    def chunk(
        self,
        document: ParsedDocument,
        *,
        document_id: str,
        workspace_id: str,
        file_id: str,
    ) -> list[DocumentChunk]:
        by_id = {
            block.block_id: block
            for page in document.pages
            for block in page.blocks
            if block.role == "body"
        }
        sections = document.sections or [
            _fallback_section(document, list(by_id))
        ]
        chunks: list[DocumentChunk] = []
        children: list[DocumentChunk] = []
        for section in sections:
            blocks = [by_id[block_id] for block_id in section.block_ids if block_id in by_id]
            if not blocks:
                continue
            parent_id = uuid4().hex
            parent = _chunk_from_blocks(
                parent_id,
                document_id,
                workspace_id,
                file_id,
                None,
                "parent",
                [section.title],
                blocks,
            )
            chunks.append(parent)
            current: list[TextBlock] = []
            size = 0
            for block in blocks:
                if current and size + len(block.text) > self._limit:
                    children.append(
                        _chunk_from_blocks(
                            uuid4().hex,
                            document_id,
                            workspace_id,
                            file_id,
                            parent_id,
                            "child",
                            [section.title],
                            current,
                        )
                    )
                    current, size = [], 0
                current.append(block)
                size += len(block.text)
            if current:
                children.append(
                    _chunk_from_blocks(
                        uuid4().hex,
                        document_id,
                        workspace_id,
                        file_id,
                        parent_id,
                        "child",
                        [section.title],
                        current,
                    )
                )
        linked = []
        for index, child in enumerate(children):
            linked.append(
                child.model_copy(
                    update={
                        "previous_chunk_id": (
                            children[index - 1].chunk_id if index > 0 else None
                        ),
                        "next_chunk_id": (
                            children[index + 1].chunk_id
                            if index + 1 < len(children)
                            else None
                        ),
                    }
                )
            )
        return [*chunks, *linked]


class DocumentIndexer:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        embeddings: EmbeddingClient,
        *,
        embedding_model: str,
        chunker: StructureAwareChunker | None = None,
    ) -> None:
        self._sessions = session_factory
        self._embeddings = embeddings
        self._embedding_model = embedding_model
        self._chunker = chunker or StructureAwareChunker()

    async def index(
        self,
        workspace_id: str,
        file_id: str,
        file_data: bytes,
        document: ParsedDocument,
    ) -> list[DocumentChunk]:
        checksum = hashlib.sha256(file_data).hexdigest()
        with self._sessions() as session:
            existing = session.scalar(
                select(ParsedDocumentModel).where(
                    ParsedDocumentModel.workspace_id == workspace_id,
                    ParsedDocumentModel.file_id == file_id,
                    ParsedDocumentModel.checksum == checksum,
                )
            )
            if existing is not None:
                return _load_chunks(session, existing.id)
        document_id = uuid4().hex
        chunks = self._chunker.chunk(
            document,
            document_id=document_id,
            workspace_id=workspace_id,
            file_id=file_id,
        )
        texts = [chunk.text for chunk in chunks]
        vectors = await self._embeddings.embed_batch(texts)
        indexed = [
            chunk.model_copy(
                update={
                    "embedding": _pad(vector),
                    "embedding_model": self._embedding_model,
                }
            )
            for chunk, vector in zip(chunks, vectors)
        ]
        with self._sessions() as session:
            session.add(
                ParsedDocumentModel(
                    id=document_id,
                    workspace_id=workspace_id,
                    file_id=file_id,
                    checksum=checksum,
                    parser_name=document.parser_name,
                    parser_version=document.parser_version,
                    page_count=document.page_count,
                    quality_score=int(document.quality.score * 100),
                    metadata_json={"filename": document.filename},
                )
            )
            session.flush()
            for chunk in indexed:
                session.add(_chunk_model(chunk))
            session.commit()
        return indexed

    def delete(self, workspace_id: str, file_id: str) -> None:
        with self._sessions() as session:
            documents = session.scalars(
                select(ParsedDocumentModel).where(
                    ParsedDocumentModel.workspace_id == workspace_id,
                    ParsedDocumentModel.file_id == file_id,
                )
            ).all()
            ids = [document.id for document in documents]
            if ids:
                session.execute(
                    delete(DocumentChunkModel).where(
                        DocumentChunkModel.document_id.in_(ids)
                    )
                )
                session.execute(
                    delete(ParsedDocumentModel).where(
                        ParsedDocumentModel.id.in_(ids)
                    )
                )
            session.commit()


def _fallback_section(document: ParsedDocument, block_ids: list[str]):  # type: ignore[no-untyped-def]
    from document_processing.schema import DocumentSection

    return DocumentSection(
        section_id="section-1",
        title="Document",
        level=1,
        page_start=1,
        page_end=max(1, document.page_count),
        block_ids=block_ids,
    )


def _chunk_from_blocks(
    chunk_id: str,
    document_id: str,
    workspace_id: str,
    file_id: str,
    parent_chunk_id: str | None,
    level: str,
    section_path: list[str],
    blocks: list[TextBlock],
) -> DocumentChunk:
    return DocumentChunk(
        chunk_id=chunk_id,
        document_id=document_id,
        workspace_id=workspace_id,
        file_id=file_id,
        parent_chunk_id=parent_chunk_id,
        level=level,
        section_path=section_path,
        text="\n".join(block.text for block in blocks),
        page_start=min(block.page_number for block in blocks),
        page_end=max(block.page_number for block in blocks),
        bbox=BoundingBox(
            x0=min(block.bbox.x0 for block in blocks),
            y0=min(block.bbox.y0 for block in blocks),
            x1=max(block.bbox.x1 for block in blocks),
            y1=max(block.bbox.y1 for block in blocks),
        ),
        source_block_ids=[block.block_id for block in blocks],
    )


def _pad(vector: list[float], dimension: int = 1024) -> list[float]:
    return (vector + [0.0] * dimension)[:dimension]


def _chunk_model(chunk: DocumentChunk) -> DocumentChunkModel:
    return DocumentChunkModel(
        id=chunk.chunk_id,
        workspace_id=chunk.workspace_id,
        file_id=chunk.file_id,
        document_id=chunk.document_id,
        parent_chunk_id=chunk.parent_chunk_id,
        level=chunk.level,
        section_path=chunk.section_path,
        text=chunk.text,
        page_start=chunk.page_start,
        page_end=chunk.page_end,
        bbox_json=[
            chunk.bbox.x0,
            chunk.bbox.y0,
            chunk.bbox.x1,
            chunk.bbox.y1,
        ],
        source_block_ids=chunk.source_block_ids,
        previous_chunk_id=chunk.previous_chunk_id,
        next_chunk_id=chunk.next_chunk_id,
        embedding=chunk.embedding,
        embedding_model=chunk.embedding_model,
        searchable_text=f"{' / '.join(chunk.section_path)}\n{chunk.text}",
    )


def _load_chunks(session: Session, document_id: str) -> list[DocumentChunk]:
    models = session.scalars(
        select(DocumentChunkModel)
        .where(DocumentChunkModel.document_id == document_id)
        .order_by(DocumentChunkModel.created_at, DocumentChunkModel.id)
    ).all()
    return [
        DocumentChunk(
            chunk_id=model.id,
            document_id=model.document_id,
            workspace_id=model.workspace_id,
            file_id=model.file_id,
            parent_chunk_id=model.parent_chunk_id,
            level=model.level,
            section_path=model.section_path,
            text=model.text,
            page_start=model.page_start,
            page_end=model.page_end,
            bbox=BoundingBox(
                x0=model.bbox_json[0],
                y0=model.bbox_json[1],
                x1=model.bbox_json[2],
                y1=model.bbox_json[3],
            ),
            source_block_ids=model.source_block_ids,
            previous_chunk_id=model.previous_chunk_id,
            next_chunk_id=model.next_chunk_id,
            embedding=model.embedding,
            embedding_model=model.embedding_model,
        )
        for model in models
    ]
