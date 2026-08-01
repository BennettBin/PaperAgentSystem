"""Structure-aware parent/child chunking and idempotent indexing."""

from __future__ import annotations

import hashlib
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from backend.core.ports.llm_client import EmbeddingClient, EmbeddingProfile
from backend.document_processing.schema import (
    BoundingBox,
    DocumentSection,
    ParsedDocument,
    TextBlock,
)
from backend.infrastructure.postgres.models import (
    DocumentChunkModel,
    DocumentSectionModel,
    ParsedDocumentModel,
)
from backend.rag.schema import DocumentChunk

CURRENT_INDEX_VERSION = 4
CURRENT_SECTION_SCHEMA_VERSION = 1


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
        sections = _document_sections(document)
        chunks: list[DocumentChunk] = []
        for section in sections:
            blocks = [by_id[block_id] for block_id in section.block_ids if block_id in by_id]
            heading = by_id.get(section.heading_block_id)
            parent_blocks = ([heading] if heading is not None else []) + blocks
            if not parent_blocks:
                continue
            parent_id = uuid4().hex
            parent = _chunk_from_blocks(
                parent_id,
                document_id,
                workspace_id,
                file_id,
                None,
                "parent",
                section,
                parent_blocks,
                0,
            )
            chunks.append(parent)
            section_children: list[DocumentChunk] = []
            current: list[TextBlock] = []
            size = 0
            for block in blocks:
                if current and size + len(block.text) > self._limit:
                    section_children.append(
                        _chunk_from_blocks(
                            uuid4().hex,
                            document_id,
                            workspace_id,
                            file_id,
                            parent_id,
                            "child",
                            section,
                            current,
                            len(section_children),
                        )
                    )
                    current, size = [], 0
                current.append(block)
                size += len(block.text)
            if current:
                section_children.append(
                    _chunk_from_blocks(
                        uuid4().hex,
                        document_id,
                        workspace_id,
                        file_id,
                        parent_id,
                        "child",
                        section,
                        current,
                        len(section_children),
                    )
                )
            for index, child in enumerate(section_children):
                chunks.append(
                    child.model_copy(
                        update={
                            "previous_chunk_id": (
                                section_children[index - 1].chunk_id
                                if index > 0
                                else None
                            ),
                            "next_chunk_id": (
                                section_children[index + 1].chunk_id
                                if index + 1 < len(section_children)
                                else None
                            ),
                        }
                    )
                )
        return chunks


class DocumentIndexer:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        embeddings: EmbeddingClient,
        *,
        embedding_model: str | None = None,
        chunker: StructureAwareChunker | None = None,
    ) -> None:
        self._sessions = session_factory
        self._embeddings = embeddings
        self._embedding_model = embedding_model
        self._chunker = chunker or StructureAwareChunker()

    def is_current(
        self,
        workspace_id: str,
        file_id: str,
        *,
        expected_checksum: str | None = None,
    ) -> bool:
        with self._sessions() as session:
            statement = (
                select(ParsedDocumentModel)
                .where(
                    ParsedDocumentModel.workspace_id == workspace_id,
                    ParsedDocumentModel.file_id == file_id,
                )
                .order_by(ParsedDocumentModel.created_at.desc())
            )
            if expected_checksum is not None:
                statement = statement.where(
                    ParsedDocumentModel.checksum == expected_checksum
                )
            document = session.scalar(statement)
            return bool(
                document is not None
                and _stored_index_is_current(
                    session,
                    document,
                    embedding_fingerprint=self._fingerprint(),
                )
            )

    async def index(
        self,
        workspace_id: str,
        file_id: str,
        file_data: bytes,
        document: ParsedDocument,
    ) -> list[DocumentChunk]:
        document = _remove_postgresql_nul_characters(document)
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
                if _stored_index_is_current(
                    session,
                    existing,
                    embedding_fingerprint=self._fingerprint(),
                ):
                    return _load_chunks(session, existing.id)
                session.execute(
                    delete(DocumentChunkModel).where(
                        DocumentChunkModel.document_id == existing.id
                    )
                )
                session.execute(
                    delete(DocumentSectionModel).where(
                        DocumentSectionModel.document_id == existing.id
                    )
                )
                session.delete(existing)
                session.commit()
        document_id = uuid4().hex
        chunks = self._chunker.chunk(
            document,
            document_id=document_id,
            workspace_id=workspace_id,
            file_id=file_id,
        )
        texts = [chunk.text for chunk in chunks]
        vectors = await self._embeddings.embed_batch(texts)
        if len(vectors) != len(chunks):
            raise RuntimeError("Embedding provider returned an unexpected vector count")
        profile = self._profile()
        fingerprint = self._fingerprint()
        strict_dimension = getattr(self._embeddings, "profile", None) is not None
        indexed = [
            chunk.model_copy(
                update={
                    "embedding": _coerce_vector(
                        vector, profile.dimension, strict=strict_dimension
                    ),
                    "embedding_model": profile.model_name,
                    "embedding_provider": profile.provider,
                    "embedding_version": profile.model_version,
                    "embedding_dimension": profile.dimension,
                    "embedding_max_length": profile.max_length,
                    "embedding_normalized": profile.normalized,
                    "embedding_fingerprint": fingerprint,
                    "embedding_status": "ready",
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
                    metadata_json={
                        "filename": document.filename,
                        "index_version": CURRENT_INDEX_VERSION,
                        "section_schema_version": CURRENT_SECTION_SCHEMA_VERSION,
                        "embedding_profile": {
                            "provider": profile.provider,
                            "model_name": profile.model_name,
                            "model_version": profile.model_version,
                            "dimension": profile.dimension,
                            "max_length": profile.max_length,
                            "normalized": profile.normalized,
                            "fingerprint": fingerprint,
                        },
                        "page_layouts": [
                            {
                                "page": page.page_number,
                                "layout": page.layout,
                                "column_count": page.column_count,
                            }
                            for page in document.pages
                        ],
                        "visual_artifacts": [
                            artifact.model_dump(mode="json", exclude={"image_png"})
                            for artifact in document.visual_artifacts
                        ],
                    },
                )
            )
            session.flush()
            for section in _document_sections(document):
                session.add(
                    _section_model(
                        document_id,
                        workspace_id,
                        file_id,
                        section,
                    )
                )
            for chunk in indexed:
                session.add(_chunk_model(chunk))
            session.commit()
        return indexed

    def _profile(self) -> EmbeddingProfile:
        profile = getattr(self._embeddings, "profile", None)
        if isinstance(profile, EmbeddingProfile):
            return profile
        if self._embedding_model is None:
            raise ValueError("Versioned embedding metadata is required for indexing")
        return EmbeddingProfile(
            provider="legacy",
            model_name=self._embedding_model,
            model_version="unknown",
            dimension=1024,
            max_length=0,
            normalized=False,
        )

    def _fingerprint(self) -> str:
        profile = getattr(self._embeddings, "profile", None)
        if isinstance(profile, EmbeddingProfile):
            return profile.fingerprint
        if self._embedding_model is None:
            raise ValueError("Versioned embedding metadata is required for indexing")
        return self._embedding_model

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
                    delete(DocumentSectionModel).where(
                        DocumentSectionModel.document_id.in_(ids)
                    )
                )
                session.execute(
                    delete(ParsedDocumentModel).where(
                        ParsedDocumentModel.id.in_(ids)
                    )
                )
            session.commit()


def _remove_postgresql_nul_characters(document: ParsedDocument) -> ParsedDocument:
    """Remove NUL characters from parsed PDF text before indexing."""

    def clean(value: str) -> str:
        return value.replace("\x00", "")

    return document.model_copy(
        update={
            "pages": [
                page.model_copy(
                    update={
                        "text": clean(page.text),
                        "blocks": [
                            block.model_copy(update={"text": clean(block.text)})
                            for block in page.blocks
                        ],
                    }
                )
                for page in document.pages
            ],
            "sections": [
                section.model_copy(
                    update={
                        "number": clean(section.number) if section.number else None,
                        "title": clean(section.title),
                        "normalized_title": clean(section.normalized_title),
                        "section_path": [clean(value) for value in section.section_path],
                    }
                )
                for section in document.sections
            ],
            "headers": [clean(value) for value in document.headers],
            "footers": [clean(value) for value in document.footers],
            "full_text": clean(document.full_text),
            "visual_artifacts": [
                artifact.model_copy(
                    update={
                        "label": clean(artifact.label),
                        "caption": clean(artifact.caption),
                        "section_path": [
                            clean(value) for value in artifact.section_path
                        ],
                    }
                )
                for artifact in document.visual_artifacts
            ],
        }
    )


def _fallback_section(
    document: ParsedDocument, block_ids: list[str]
) -> DocumentSection:
    return DocumentSection(
        section_id="section-1",
        number=None,
        title="Document",
        normalized_title="document",
        level=1,
        section_path=["Document"],
        page_start=1,
        page_end=max(1, document.page_count),
        heading_block_id=block_ids[0] if block_ids else "",
        block_ids=block_ids,
        ordinal=0,
    )


def _document_sections(document: ParsedDocument) -> list[DocumentSection]:
    if document.sections:
        return document.sections
    block_ids = [
        block.block_id
        for page in document.pages
        for block in page.blocks
        if block.role == "body"
    ]
    return [_fallback_section(document, block_ids)]


def _stored_index_is_current(
    session: Session,
    document: ParsedDocumentModel,
    *,
    embedding_fingerprint: str,
) -> bool:
    metadata = document.metadata_json or {}
    if metadata.get("index_version") != CURRENT_INDEX_VERSION:
        return False
    if metadata.get("section_schema_version") != CURRENT_SECTION_SCHEMA_VERSION:
        return False
    section_count = session.query(DocumentSectionModel).filter(
        DocumentSectionModel.document_id == document.id
    ).count()
    if section_count < 1:
        return False
    chunks = _load_chunks(session, document.id)
    return bool(
        chunks
        and all(
            (chunk.embedding_fingerprint or chunk.embedding_model)
            == embedding_fingerprint
            and chunk.embedding_status == "ready"
            and chunk.section_id != "unknown"
            for chunk in chunks
        )
    )


def _chunk_from_blocks(
    chunk_id: str,
    document_id: str,
    workspace_id: str,
    file_id: str,
    parent_chunk_id: str | None,
    level: str,
    section: DocumentSection,
    blocks: list[TextBlock],
    chunk_index_in_section: int,
) -> DocumentChunk:
    return DocumentChunk(
        chunk_id=chunk_id,
        document_id=document_id,
        workspace_id=workspace_id,
        file_id=file_id,
        parent_chunk_id=parent_chunk_id,
        level=level,
        section_id=section.section_id,
        section_number=section.number,
        section_title=section.title,
        section_path=section.section_path or [section.title],
        chunk_index_in_section=chunk_index_in_section,
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


def _coerce_vector(
    vector: list[float], dimension: int = 1024, *, strict: bool
) -> list[float]:
    if strict and len(vector) != dimension:
        raise RuntimeError(
            f"Embedding provider returned {len(vector)} dimensions; expected {dimension}"
        )
    return (vector + [0.0] * dimension)[:dimension]


def _chunk_model(chunk: DocumentChunk) -> DocumentChunkModel:
    return DocumentChunkModel(
        id=chunk.chunk_id,
        workspace_id=chunk.workspace_id,
        file_id=chunk.file_id,
        document_id=chunk.document_id,
        parent_chunk_id=chunk.parent_chunk_id,
        level=chunk.level,
        section_id=chunk.section_id,
        section_number=chunk.section_number,
        section_title=chunk.section_title,
        section_path=chunk.section_path,
        chunk_index_in_section=chunk.chunk_index_in_section,
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
        embedding_provider=chunk.embedding_provider,
        embedding_version=chunk.embedding_version,
        embedding_dimension=chunk.embedding_dimension,
        embedding_max_length=chunk.embedding_max_length,
        embedding_normalized=chunk.embedding_normalized,
        embedding_fingerprint=chunk.embedding_fingerprint,
        embedding_status=chunk.embedding_status,
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
            section_id=model.section_id or "unknown",
            section_number=model.section_number,
            section_title=model.section_title or (
                model.section_path[-1] if model.section_path else "Unknown"
            ),
            section_path=model.section_path,
            chunk_index_in_section=model.chunk_index_in_section or 0,
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
            embedding_provider=model.embedding_provider,
            embedding_version=model.embedding_version,
            embedding_dimension=model.embedding_dimension,
            embedding_max_length=model.embedding_max_length,
            embedding_normalized=model.embedding_normalized,
            embedding_fingerprint=model.embedding_fingerprint,
            embedding_status=model.embedding_status,
        )
        for model in models
    ]


def _section_model(
    document_id: str,
    workspace_id: str,
    file_id: str,
    section: DocumentSection,
) -> DocumentSectionModel:
    return DocumentSectionModel(
        id=uuid4().hex,
        workspace_id=workspace_id,
        file_id=file_id,
        document_id=document_id,
        section_id=section.section_id,
        number=section.number,
        title=section.title,
        normalized_title=section.normalized_title,
        level=section.level,
        parent_section_id=section.parent_section_id,
        section_path=section.section_path,
        ordinal=section.ordinal,
        page_start=section.page_start,
        page_end=section.page_end,
        heading_block_id=section.heading_block_id,
        block_ids=section.block_ids,
        descendant_block_ids=section.descendant_block_ids,
        schema_version=1,
    )
