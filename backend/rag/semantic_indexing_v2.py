"""Semantic multimodal chunking and idempotent persistence for CanonicalDocument V2."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from backend.core.ports.llm_client import EmbeddingClient, EmbeddingProfile
from backend.document_processing.markdown_v2 import CanonicalMarkdownRenderer
from backend.document_processing.schema import BoundingBox
from backend.document_processing.schema_v2 import (
    CanonicalDocumentV2,
    DocumentElement,
    ElementType,
    EvidenceSpan,
    LocatorType,
    StructuredTable,
    stable_identifier,
)
from backend.infrastructure.postgres.models import (
    DocumentChunkModel,
    DocumentSectionModel,
    ParsedDocumentModel,
)
from backend.rag.schema import DocumentChunk

CURRENT_INDEX_VERSION = 5
CURRENT_SECTION_SCHEMA_VERSION = 2

_BODY_TYPES = {
    ElementType.TITLE,
    ElementType.PARAGRAPH,
    ElementType.LIST_ITEM,
    ElementType.FOOTNOTE,
    ElementType.CODE,
    ElementType.ALGORITHM,
    ElementType.REFERENCE,
    ElementType.UNKNOWN,
}


@dataclass(frozen=True, slots=True)
class _SectionView:
    section_id: str
    number: str | None
    title: str
    level: int
    parent_section_id: str | None
    section_path: tuple[str, ...]
    page_start: int
    page_end: int
    heading_element_id: str
    element_ids: tuple[str, ...]
    ordinal: int


class SemanticChunkerV2:
    """Split by document semantics while preserving every source geometry span."""

    def __init__(self, child_character_limit: int = 700) -> None:
        if child_character_limit < 1:
            raise ValueError("child_character_limit must be positive")
        self._limit = child_character_limit

    def chunk(
        self,
        document: CanonicalDocumentV2,
        *,
        document_id: str,
        workspace_id: str,
        file_id: str,
    ) -> list[DocumentChunk]:
        elements = [element for page in document.pages for element in page.elements]
        by_id = {element.element_id: element for element in elements}
        tables_by_source = {
            source_id: table
            for table in document.tables
            for source_id in table.source_element_ids
        }
        equations_by_source = {
            source_id: equation
            for equation in document.equations
            for source_id in equation.source_element_ids
        }
        figures_by_source = {
            source_id: figure
            for figure in document.figures
            for source_id in figure.source_element_ids
        }
        sections = self._sections(document, elements)
        chunks: list[DocumentChunk] = []
        for section in sections:
            section_elements = [by_id[item] for item in section.element_ids if item in by_id]
            child_specs: list[tuple[str, str, list[DocumentElement], list[ElementType], bool]] = []
            body: list[DocumentElement] = []
            body_size = 0

            def flush_body() -> None:
                nonlocal body, body_size
                if body:
                    child_specs.append(
                        (
                            "body",
                            "\n".join(item.text for item in body if item.text),
                            list(body),
                            self._unique_types(body),
                            any(item.is_inferred for item in body),
                        )
                    )
                body, body_size = [], 0

            rendered_tables: set[str] = set()
            rendered_equations: set[str] = set()
            rendered_figures: set[str] = set()
            artifact_source_ids = set(tables_by_source) | set(equations_by_source) | set(figures_by_source)
            for element in section_elements:
                if element.element_type in _BODY_TYPES:
                    if body and body_size + len(element.text) > self._limit:
                        flush_body()
                    body.append(element)
                    body_size += len(element.text)
                    continue
                if element.element_type is ElementType.TABLE:
                    flush_body()
                    table = tables_by_source.get(element.element_id)
                    if table is not None and table.table_id not in rendered_tables:
                        child_specs.extend(self._table_specs(table, by_id))
                        rendered_tables.add(table.table_id)
                    continue
                if element.element_type is ElementType.EQUATION:
                    flush_body()
                    equation = equations_by_source.get(element.element_id)
                    if equation is not None and equation.equation_id not in rendered_equations:
                        context = self._nearby_context(section_elements, element)
                        text = f"Equation{f' {equation.number}' if equation.number else ''}: {equation.latex}"
                        if context:
                            text += "\nContext: " + " ".join(item.text for item in context)
                        sources = [element, *context]
                        child_specs.append(
                            (
                                "equation",
                                text,
                                sources,
                                [ElementType.EQUATION],
                                any(item.is_inferred for item in sources),
                            )
                        )
                        rendered_equations.add(equation.equation_id)
                    continue
                if element.element_type is ElementType.FIGURE:
                    flush_body()
                    figure = figures_by_source.get(element.element_id)
                    if figure is not None and figure.figure_id not in rendered_figures:
                        sources = [by_id[item] for item in figure.source_element_ids if item in by_id]
                        references = self._figure_references(section_elements, figure.caption)
                        sources = self._unique_elements([*sources, *references])
                        parts = []
                        if figure.caption:
                            parts.append(figure.caption)
                        if figure.description:
                            prefix = "[inferred description] " if figure.description_is_inferred else ""
                            parts.append(prefix + figure.description)
                        if references:
                            parts.append("Body references: " + " ".join(item.text for item in references))
                        child_specs.append(
                            (
                                "figure",
                                "\n".join(parts),
                                sources,
                                [ElementType.FIGURE],
                                figure.description_is_inferred or any(item.is_inferred for item in sources),
                            )
                        )
                        rendered_figures.add(figure.figure_id)
                    continue
                if element.element_type is ElementType.CAPTION and element.element_id not in artifact_source_ids:
                    flush_body()
                    child_specs.append(("caption", element.text, [element], [ElementType.CAPTION], element.is_inferred))
            flush_body()
            child_chunks = [
                self._chunk_from_elements(
                    document_id=document_id,
                    workspace_id=workspace_id,
                    file_id=file_id,
                    section=section,
                    level="child",
                    parent_chunk_id=None,
                    content_kind=kind,
                    text=text,
                    elements=sources,
                    element_types=element_types,
                    contains_inferred=inferred,
                    ordinal=index,
                )
                for index, (kind, text, sources, element_types, inferred) in enumerate(child_specs)
                if text.strip() and sources
            ]
            if not child_chunks:
                continue
            parent_id = stable_identifier("chunk", document_id, section.section_id, "parent")
            parent_sources = self._unique_elements(
                [element for child in child_chunks for element in self._elements_for_chunk(child, by_id)]
            )
            if not parent_sources:
                parent_sources = self._unique_elements(section_elements)
            parent = self._chunk_from_elements(
                document_id=document_id,
                workspace_id=workspace_id,
                file_id=file_id,
                section=section,
                level="parent",
                parent_chunk_id=None,
                content_kind="section_parent",
                text="\n\n".join(child.text for child in child_chunks),
                elements=parent_sources,
                element_types=self._unique_types(parent_sources),
                contains_inferred=any(child.contains_inferred_content for child in child_chunks),
                ordinal=0,
                forced_chunk_id=parent_id,
            )
            linked = [
                child.model_copy(
                    update={
                        "parent_chunk_id": parent_id,
                        "previous_chunk_id": child_chunks[index - 1].chunk_id if index else None,
                        "next_chunk_id": (
                            child_chunks[index + 1].chunk_id
                            if index + 1 < len(child_chunks)
                            else None
                        ),
                    }
                )
                for index, child in enumerate(child_chunks)
            ]
            chunks.extend((parent, *linked))
        return chunks

    @staticmethod
    def _sections(
        document: CanonicalDocumentV2, elements: list[DocumentElement]
    ) -> tuple[_SectionView, ...]:
        if document.sections:
            return tuple(
                _SectionView(
                    section_id=section.section_id,
                    number=section.number,
                    title=section.title,
                    level=section.level,
                    parent_section_id=section.parent_section_id,
                    section_path=section.section_path,
                    page_start=section.page_start,
                    page_end=section.page_end,
                    heading_element_id=section.heading_element_id,
                    element_ids=section.element_ids,
                    ordinal=section.ordinal,
                )
                for section in document.sections
            )
        return (
            _SectionView(
                section_id=stable_identifier("sec", document.document_id, "document"),
                number=None,
                title="Document",
                level=1,
                parent_section_id=None,
                section_path=("Document",),
                page_start=1,
                page_end=max(1, document.page_count),
                heading_element_id=elements[0].element_id if elements else "",
                element_ids=tuple(element.element_id for element in elements),
                ordinal=0,
            ),
        )

    def _table_specs(
        self, table: StructuredTable, by_id: dict[str, DocumentElement]
    ) -> list[tuple[str, str, list[DocumentElement], list[ElementType], bool]]:
        table_element = next(
            (
                by_id[source_id]
                for source_id in table.source_element_ids
                if source_id in by_id and by_id[source_id].element_type is ElementType.TABLE
            ),
            None,
        )
        cell_elements = [
            by_id[source_id]
            for source_id in table.source_element_ids
            if source_id in by_id and by_id[source_id].element_type is ElementType.TABLE_CELL
        ]
        captions = [
            by_id[source_id]
            for source_id in table.source_element_ids
            if source_id in by_id and by_id[source_id].element_type is ElementType.CAPTION
        ]
        base = [item for item in (table_element, *captions) if item is not None]
        row_count = max((cell.row_index for cell in table.cells), default=-1) + 1
        column_count = max((cell.column_index for cell in table.cells), default=-1) + 1
        rows: list[str] = []
        for row_index in range(row_count):
            row = sorted(
                (cell for cell in table.cells if cell.row_index == row_index),
                key=lambda cell: cell.column_index,
            )
            rows.append(" | ".join(cell.text for cell in row))
        summary_rows = [
            f"Row {row_index + 1}: "
            + "; ".join(
                f"Column {cell.column_index + 1}={cell.text}"
                for cell in sorted(
                    (item for item in table.cells if item.row_index == row_index),
                    key=lambda item: item.column_index,
                )
            )
            for row_index in range(row_count)
        ]
        specs = []
        if table.caption and base:
            specs.append(
                (
                    "table_caption",
                    f"Table caption: {table.caption}",
                    base,
                    [ElementType.TABLE, ElementType.CAPTION],
                    any(item.is_inferred for item in base),
                )
            )
        cell_sources = self._unique_elements([*([table_element] if table_element else []), *cell_elements])
        if cell_sources:
            specs.append(
                (
                    "table_cells",
                    "Table cells:\n" + "\n".join(rows),
                    cell_sources,
                    [ElementType.TABLE, ElementType.TABLE_CELL],
                    any(item.is_inferred for item in cell_sources),
                )
            )
            specs.append(
                (
                    "table_summary",
                    f"Table with {row_count} rows and {column_count} columns. "
                    + " ".join(summary_rows),
                    cell_sources,
                    [ElementType.TABLE, ElementType.TABLE_CELL],
                    any(item.is_inferred for item in cell_sources),
                )
            )
        return specs

    @staticmethod
    def _nearby_context(
        elements: list[DocumentElement], target: DocumentElement
    ) -> list[DocumentElement]:
        index = elements.index(target)
        result: list[DocumentElement] = []
        for direction in (-1, 1):
            position = index + direction
            while 0 <= position < len(elements):
                candidate = elements[position]
                if candidate.element_type in {ElementType.PARAGRAPH, ElementType.LIST_ITEM}:
                    result.append(candidate)
                    break
                position += direction
        return sorted(result, key=lambda item: (item.page_number, item.reading_order))

    @staticmethod
    def _figure_references(
        elements: list[DocumentElement], caption: str
    ) -> list[DocumentElement]:
        match = re.search(r"\b(?:figure|fig\.)\s*\d+", caption, re.I)
        if match is None:
            return []
        label = match.group(0).casefold()
        return [
            element
            for element in elements
            if element.element_type in {ElementType.PARAGRAPH, ElementType.LIST_ITEM}
            and label in element.text.casefold()
        ]

    @staticmethod
    def _unique_elements(elements: list[DocumentElement]) -> list[DocumentElement]:
        return list({element.element_id: element for element in elements}.values())

    @staticmethod
    def _unique_types(elements: list[DocumentElement]) -> list[ElementType]:
        return list(dict.fromkeys(element.element_type for element in elements))

    @staticmethod
    def _elements_for_chunk(
        chunk: DocumentChunk, by_id: dict[str, DocumentElement]
    ) -> list[DocumentElement]:
        return [by_id[source_id] for source_id in chunk.source_block_ids if source_id in by_id]

    def _chunk_from_elements(
        self,
        *,
        document_id: str,
        workspace_id: str,
        file_id: str,
        section: _SectionView,
        level: str,
        parent_chunk_id: str | None,
        content_kind: str,
        text: str,
        elements: list[DocumentElement],
        element_types: list[ElementType],
        contains_inferred: bool,
        ordinal: int,
        forced_chunk_id: str | None = None,
    ) -> DocumentChunk:
        elements = self._unique_elements(elements)
        spans = [
            EvidenceSpan(
                element_id=element.element_id,
                page_number=element.page_number,
                locator_type=LocatorType(
                    str(element.metadata.get("locator_type", LocatorType.PDF_PAGE.value))
                ),
                bbox=element.bbox,
                normalized_bbox=element.normalized_bbox,
                source_parser=element.provenance.parser_name,
            )
            for element in elements
        ]
        first_bbox = spans[0].bbox
        chunk_id = forced_chunk_id or stable_identifier(
            "chunk",
            document_id,
            section.section_id,
            content_kind,
            ordinal,
            *(span.element_id for span in spans),
        )
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
            section_path=list(section.section_path),
            chunk_index_in_section=ordinal,
            text=text,
            page_start=min(span.page_number for span in spans),
            page_end=max(span.page_number for span in spans),
            bbox=BoundingBox(
                x0=first_bbox.x0,
                y0=first_bbox.y0,
                x1=first_bbox.x1,
                y1=first_bbox.y1,
            ),
            source_block_ids=[span.element_id for span in spans],
            evidence_spans=spans,
            element_types=element_types,
            content_kind=content_kind,
            contains_inferred_content=contains_inferred,
        )


class DocumentIndexerV2:
    """Persist Canonical JSON, derived Markdown and semantic chunks idempotently."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        embeddings: EmbeddingClient,
        *,
        embedding_model: str | None = None,
        chunker: SemanticChunkerV2 | None = None,
        renderer: CanonicalMarkdownRenderer | None = None,
    ) -> None:
        self._sessions = session_factory
        self._embeddings = embeddings
        self._embedding_model = embedding_model
        self._chunker = chunker or SemanticChunkerV2()
        self._renderer = renderer or CanonicalMarkdownRenderer()

    async def index(
        self,
        workspace_id: str,
        file_id: str,
        file_data: bytes,
        document: CanonicalDocumentV2,
        *,
        visual_artifacts: list[dict[str, object]] | None = None,
    ) -> list[DocumentChunk]:
        checksum = hashlib.sha256(file_data).hexdigest()
        if checksum != document.checksum:
            raise ValueError("file checksum does not match CanonicalDocument V2")
        if not document.quality.ready_for_index:
            raise ValueError("CanonicalDocument V2 is not ready for indexing")
        fingerprint = self._fingerprint()
        with self._sessions() as session:
            existing_documents = session.scalars(
                select(ParsedDocumentModel).where(
                    ParsedDocumentModel.workspace_id == workspace_id,
                    ParsedDocumentModel.file_id == file_id,
                    ParsedDocumentModel.checksum == checksum,
                )
            ).all()
            current = [
                stored
                for stored in existing_documents
                if self._stored_is_current(
                    session, stored, document.pipeline_fingerprint, fingerprint
                )
            ]
            if len(current) == 1 and len(existing_documents) == 1:
                return self._load_chunks(session, current[0].id)

        document_id = uuid4().hex
        chunks = self._chunker.chunk(
            document,
            document_id=document_id,
            workspace_id=workspace_id,
            file_id=file_id,
        )
        vectors = await self._embeddings.embed_batch([chunk.text for chunk in chunks])
        if len(vectors) != len(chunks):
            raise RuntimeError("Embedding provider returned an unexpected vector count")
        profile = self._profile()
        strict = getattr(self._embeddings, "profile", None) is not None
        indexed = [
            chunk.model_copy(
                update={
                    "embedding": self._coerce_vector(vector, profile.dimension, strict=strict),
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
        markdown = self._renderer.render(document)
        with self._sessions() as session:
            existing_documents = session.scalars(
                select(ParsedDocumentModel).where(
                    ParsedDocumentModel.workspace_id == workspace_id,
                    ParsedDocumentModel.file_id == file_id,
                    ParsedDocumentModel.checksum == checksum,
                )
            ).all()
            for existing in existing_documents:
                self._delete_document(session, existing.id)
            session.flush()
            session.add(
                ParsedDocumentModel(
                    id=document_id,
                    workspace_id=workspace_id,
                    file_id=file_id,
                    checksum=checksum,
                    parser_name="hybrid-document-v2",
                    parser_version=document.schema_version,
                    page_count=document.page_count,
                    quality_score=int(document.quality.overall * 100),
                    metadata_json={
                        "filename": document.filename,
                        "index_version": CURRENT_INDEX_VERSION,
                        "section_schema_version": CURRENT_SECTION_SCHEMA_VERSION,
                        "document_schema_version": document.schema_version,
                        "pipeline_fingerprint": document.pipeline_fingerprint,
                        "embedding_fingerprint": fingerprint,
                        "canonical_document": document.model_dump(mode="json"),
                        "derived_markdown": markdown.model_dump(mode="json"),
                        "visual_artifacts": visual_artifacts or [],
                    },
                )
            )
            session.flush()
            for section in SemanticChunkerV2._sections(
                document, [element for page in document.pages for element in page.elements]
            ):
                session.add(self._section_model(document_id, workspace_id, file_id, section))
            for chunk in indexed:
                session.add(self._chunk_model(chunk))
            session.commit()
        return indexed

    def is_current(
        self,
        workspace_id: str,
        file_id: str,
        *,
        expected_checksum: str,
        expected_pipeline_fingerprint: str,
    ) -> bool:
        with self._sessions() as session:
            documents = session.scalars(
                select(ParsedDocumentModel).where(
                    ParsedDocumentModel.workspace_id == workspace_id,
                    ParsedDocumentModel.file_id == file_id,
                    ParsedDocumentModel.checksum == expected_checksum,
                )
            ).all()
            return bool(
                len(documents) == 1
                and self._stored_is_current(
                    session,
                    documents[0],
                    expected_pipeline_fingerprint,
                    self._fingerprint(),
                )
            )

    def delete(self, workspace_id: str, file_id: str) -> None:
        with self._sessions() as session:
            documents = session.scalars(
                select(ParsedDocumentModel).where(
                    ParsedDocumentModel.workspace_id == workspace_id,
                    ParsedDocumentModel.file_id == file_id,
                )
            ).all()
            for document in documents:
                self._delete_document(session, document.id)
            session.commit()

    def _profile(self) -> EmbeddingProfile:
        profile = getattr(self._embeddings, "profile", None)
        if isinstance(profile, EmbeddingProfile):
            return profile
        if self._embedding_model is None:
            raise ValueError("Versioned embedding metadata is required for indexing")
        return EmbeddingProfile("legacy", self._embedding_model, "unknown", 1024, 0, False)

    def _fingerprint(self) -> str:
        profile = getattr(self._embeddings, "profile", None)
        if isinstance(profile, EmbeddingProfile):
            return profile.fingerprint
        if self._embedding_model is None:
            raise ValueError("Versioned embedding metadata is required for indexing")
        return self._embedding_model

    @staticmethod
    def _coerce_vector(vector: list[float], dimension: int, *, strict: bool) -> list[float]:
        if strict and len(vector) != dimension:
            raise RuntimeError(
                f"Embedding provider returned {len(vector)} dimensions; expected {dimension}"
            )
        return (vector + [0.0] * dimension)[:dimension]

    @staticmethod
    def _delete_document(session: Session, document_id: str) -> None:
        session.execute(delete(DocumentChunkModel).where(DocumentChunkModel.document_id == document_id))
        session.execute(delete(DocumentSectionModel).where(DocumentSectionModel.document_id == document_id))
        session.execute(delete(ParsedDocumentModel).where(ParsedDocumentModel.id == document_id))

    @staticmethod
    def _stored_is_current(
        session: Session,
        document: ParsedDocumentModel,
        pipeline_fingerprint: str,
        embedding_fingerprint: str,
    ) -> bool:
        metadata = document.metadata_json or {}
        if metadata.get("index_version") != CURRENT_INDEX_VERSION:
            return False
        if metadata.get("section_schema_version") != CURRENT_SECTION_SCHEMA_VERSION:
            return False
        if metadata.get("document_schema_version") != "2.0":
            return False
        if metadata.get("pipeline_fingerprint") != pipeline_fingerprint:
            return False
        chunks = DocumentIndexerV2._load_chunks(session, document.id)
        return bool(
            chunks
            and all(
                chunk.embedding_status == "ready"
                and (chunk.embedding_fingerprint or chunk.embedding_model) == embedding_fingerprint
                and chunk.evidence_spans
                for chunk in chunks
            )
        )

    @staticmethod
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
            bbox_json=[chunk.bbox.x0, chunk.bbox.y0, chunk.bbox.x1, chunk.bbox.y1],
            source_block_ids=chunk.source_block_ids,
            evidence_spans=[span.model_dump(mode="json") for span in chunk.evidence_spans],
            element_types=[element_type.value for element_type in chunk.element_types],
            content_kind=chunk.content_kind,
            contains_inferred_content=chunk.contains_inferred_content,
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

    @staticmethod
    def _load_chunks(session: Session, document_id: str) -> list[DocumentChunk]:
        models = session.scalars(
            select(DocumentChunkModel).where(DocumentChunkModel.document_id == document_id)
        ).all()
        models = sorted(
            models,
            key=lambda model: (
                0 if model.level == "parent" else 1,
                model.chunk_index_in_section or 0,
                model.id,
            ),
        )
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
                section_title=model.section_title or "Unknown",
                section_path=list(model.section_path or []),
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
                source_block_ids=list(model.source_block_ids or []),
                evidence_spans=[
                    EvidenceSpan.model_validate(span)
                    for span in (model.evidence_spans or [])
                ],
                element_types=[
                    ElementType(element_type)
                    for element_type in (model.element_types or [])
                ],
                content_kind=model.content_kind or "body",
                contains_inferred_content=bool(model.contains_inferred_content),
                previous_chunk_id=model.previous_chunk_id,
                next_chunk_id=model.next_chunk_id,
                embedding=list(model.embedding),
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

    @staticmethod
    def _section_model(
        document_id: str,
        workspace_id: str,
        file_id: str,
        section: _SectionView,
    ) -> DocumentSectionModel:
        return DocumentSectionModel(
            id=uuid4().hex,
            workspace_id=workspace_id,
            file_id=file_id,
            document_id=document_id,
            section_id=section.section_id,
            number=section.number,
            title=section.title,
            normalized_title=section.title.casefold(),
            level=section.level,
            parent_section_id=section.parent_section_id,
            section_path=list(section.section_path),
            ordinal=section.ordinal,
            page_start=section.page_start,
            page_end=section.page_end,
            heading_block_id=section.heading_element_id,
            block_ids=list(section.element_ids),
            descendant_block_ids=list(section.element_ids),
            schema_version=CURRENT_SECTION_SCHEMA_VERSION,
        )
