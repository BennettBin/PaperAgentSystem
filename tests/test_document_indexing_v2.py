from __future__ import annotations

import hashlib

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.document_processing.markdown_v2 import CanonicalMarkdownRenderer
from backend.document_processing.schema_v2 import (
    CanonicalBoundingBox,
    CanonicalDocumentV2,
    CanonicalPage,
    CanonicalSection,
    CoordinateSpace,
    DocumentElement,
    DocumentQuality,
    ElementType,
    Equation,
    Figure,
    NormalizedBoundingBox,
    PageProfile,
    PageQuality,
    ParseRoute,
    ParserProvenance,
    PipelineComponent,
    PipelineDescriptor,
    QualityStatus,
    ReconciliationDecision,
    SourceCandidate,
    StructuredTable,
    TableCell,
    stable_document_id,
    stable_element_id,
    stable_identifier,
)
from backend.infrastructure.postgres.models import (
    Base,
    DocumentChunkModel,
    ParsedDocumentModel,
)
from backend.rag.retrieval import HybridRetriever
from backend.rag.semantic_indexing_v2 import (
    CURRENT_INDEX_VERSION,
    CURRENT_SECTION_SCHEMA_VERSION,
    DocumentIndexerV2,
    SemanticChunkerV2,
)

FILE_DATA = b"canonical-document-v2-index-fixture"
CHECKSUM = hashlib.sha256(FILE_DATA).hexdigest()
PAGE_BOX = CanonicalBoundingBox(x0=0, y0=0, x1=600, y1=800)


class CountingEmbeddings:
    def __init__(self) -> None:
        self.calls = 0

    async def embed(self, text: str) -> list[float]:
        terms = ("92.4", "calibration", "energy", "trend")
        vector = [1.0 if term in text.casefold() else 0.0 for term in terms]
        return vector + [0.0] * (1024 - len(vector))

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        self.calls += len(texts)
        return [await self.embed(text) for text in texts]


class LexicalReranker:
    async def rerank(
        self, query: str, documents: list[str], top_k: int = 5
    ) -> list[tuple[int, float]]:
        terms = set(query.casefold().split())
        scored = [
            (index, float(len(terms & set(document.casefold().split()))))
            for index, document in enumerate(documents)
        ]
        return sorted(scored, key=lambda item: (-item[1], item[0]))[:top_k]


@pytest.fixture
def database(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'v2-index.db').as_posix()}")
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)


def _bbox(page: int, x0: float, y0: float, x1: float, y1: float):
    box = CanonicalBoundingBox(x0=x0, y0=y0, x1=x1, y1=y1)
    return box, NormalizedBoundingBox(
        x0=x0 / 600, y0=y0 / 800, x1=x1 / 600, y1=y1 / 800
    )


def _element(
    page: int,
    order: int,
    kind: ElementType,
    text: str,
    coords: tuple[float, float, float, float],
    *,
    parent_id: str | None = None,
    children_ids: tuple[str, ...] = (),
    inferred: bool = False,
    metadata: dict[str, str | int | float | bool | None] | None = None,
) -> DocumentElement:
    box, normalized = _bbox(page, *coords)
    provenance = ParserProvenance(
        parser_name="fixture-hybrid-v2",
        parser_version="2.0.0",
        model_name="fixture-vlm" if inferred else None,
        model_version="1" if inferred else None,
        confidence=0.98,
        source_coordinate_space=CoordinateSpace.PDF_POINT,
        is_inferred=inferred,
    )
    element_id = stable_element_id(CHECKSUM, page, kind, order, box, text)
    candidate_id = stable_identifier("cand", "fixture", element_id)
    return DocumentElement(
        element_id=element_id,
        page_number=page,
        element_type=kind,
        text=text,
        normalized_text=text,
        bbox=box,
        normalized_bbox=normalized,
        reading_order=order,
        provenance=provenance,
        parent_id=parent_id,
        children_ids=children_ids,
        source_candidates=(
            SourceCandidate(
                candidate_id=candidate_id,
                element_type=kind,
                text=text,
                bbox=box,
                normalized_bbox=normalized,
                reading_order=order,
                provenance=provenance,
                accepted=True,
                decision_reason="fixture accepted",
            ),
        ),
        is_inferred=inferred,
        metadata=metadata or {},
    )


def _quality() -> PageQuality:
    return PageQuality(
        status=QualityStatus.PASS,
        overall=0.98,
        text=0.98,
        coordinates=0.98,
        reading_order=0.98,
        structure=0.98,
        ocr=0.98,
        tables=0.98,
        completeness=0.98,
    )


def canonical_document(*, with_artifacts: bool = True) -> CanonicalDocumentV2:
    pipeline = PipelineDescriptor(
        router_version="router-v1",
        render_scale=2,
        components=(PipelineComponent(name="fixture-hybrid-v2", version="2.0.0"),),
    )
    heading = _element(1, 0, ElementType.SECTION_HEADING, "1 Results", (40, 50, 300, 85))
    paragraph_1 = _element(
        1,
        1,
        ElementType.PARAGRAPH,
        "Calibration improves on the benchmark and references Figure 1.",
        (40, 100, 560, 150),
    )
    paragraph_2 = _element(
        2,
        0,
        ElementType.PARAGRAPH,
        "The second page confirms calibration remains stable.",
        (40, 80, 560, 130),
    )
    page_1_elements: list[DocumentElement] = [heading, paragraph_1]
    page_2_elements: list[DocumentElement] = [paragraph_2]
    tables: tuple[StructuredTable, ...] = ()
    equations: tuple[Equation, ...] = ()
    figures: tuple[Figure, ...] = ()
    if with_artifacts:
        table_caption = _element(
            1, 2, ElementType.CAPTION, "Table 1 Calibration scores", (50, 180, 400, 205)
        )
        table = _element(1, 3, ElementType.TABLE, "Model Score", (50, 215, 550, 350))
        cell_1 = _element(
            1,
            4,
            ElementType.TABLE_CELL,
            "Model A",
            (50, 215, 300, 270),
            parent_id=table.element_id,
            metadata={"row_index": 0, "column_index": 0},
        )
        cell_2 = _element(
            1,
            5,
            ElementType.TABLE_CELL,
            "92.4",
            (300, 215, 550, 270),
            parent_id=table.element_id,
            metadata={"row_index": 0, "column_index": 1},
        )
        table = table.model_copy(update={"children_ids": (cell_1.element_id, cell_2.element_id)})
        equation = _element(
            1,
            6,
            ElementType.EQUATION,
            "E = mc^2",
            (100, 390, 400, 430),
            metadata={"latex": "E = mc^2", "number": "1"},
        )
        figure_caption = _element(
            2, 1, ElementType.CAPTION, "Figure 1 Calibration trend", (60, 180, 420, 210)
        )
        figure = _element(
            2,
            2,
            ElementType.FIGURE,
            "A steadily rising trend line",
            (60, 220, 540, 600),
            inferred=True,
            metadata={"content_kind": "generated_description"},
        )
        page_1_elements.extend((table_caption, table, cell_1, cell_2, equation))
        page_2_elements.extend((figure_caption, figure))
        table_cells = (
            TableCell(
                cell_id=stable_identifier("cell", cell_1.element_id),
                page_number=1,
                row_index=0,
                column_index=0,
                text=cell_1.text,
                bbox=cell_1.bbox,
                normalized_bbox=cell_1.normalized_bbox,
                confidence=0.98,
            ),
            TableCell(
                cell_id=stable_identifier("cell", cell_2.element_id),
                page_number=1,
                row_index=0,
                column_index=1,
                text=cell_2.text,
                bbox=cell_2.bbox,
                normalized_bbox=cell_2.normalized_bbox,
                confidence=0.98,
            ),
        )
        tables = (
            StructuredTable(
                table_id=stable_identifier("table", table.element_id),
                page_number=1,
                caption=table_caption.text,
                bbox=table.bbox,
                normalized_bbox=table.normalized_bbox,
                cells=table_cells,
                source_element_ids=(
                    table.element_id,
                    cell_1.element_id,
                    cell_2.element_id,
                    table_caption.element_id,
                ),
            ),
        )
        equations = (
            Equation(
                equation_id=stable_identifier("eq", equation.element_id),
                page_number=1,
                latex="E = mc^2",
                number="1",
                bbox=equation.bbox,
                normalized_bbox=equation.normalized_bbox,
                confidence=0.98,
                source_element_ids=(equation.element_id,),
            ),
        )
        figures = (
            Figure(
                figure_id=stable_identifier("fig", figure.element_id),
                page_number=2,
                caption=figure_caption.text,
                description=figure.text,
                description_is_inferred=True,
                bbox=figure.bbox,
                normalized_bbox=figure.normalized_bbox,
                source_element_ids=(figure.element_id, figure_caption.element_id),
            ),
        )
    profile_1 = PageProfile(
        page_number=1,
        native_character_count=200,
        garble_ratio=0,
        image_coverage=0,
        text_overlap_ratio=0,
        bbox_out_of_bounds_ratio=0,
        has_tables=with_artifacts,
        has_formulas=with_artifacts,
        proposed_route=ParseRoute.FAST_NATIVE,
    )
    profile_2 = profile_1.model_copy(
        update={"page_number": 2, "has_tables": False, "has_formulas": False}
    )
    pages = (
        CanonicalPage(
            page_number=1,
            width=600,
            height=800,
            cropbox=PAGE_BOX,
            selected_route=ParseRoute.FAST_NATIVE,
            profile=profile_1,
            elements=tuple(page_1_elements),
            quality=_quality(),
        ),
        CanonicalPage(
            page_number=2,
            width=600,
            height=800,
            cropbox=PAGE_BOX,
            selected_route=ParseRoute.FAST_NATIVE,
            profile=profile_2,
            elements=tuple(page_2_elements),
            quality=_quality(),
        ),
    )
    all_elements = [element for page in pages for element in page.elements]
    section = CanonicalSection(
        section_id=stable_identifier("sec", heading.element_id),
        title="1 Results",
        number="1",
        level=1,
        section_path=("1 Results",),
        page_start=1,
        page_end=2,
        heading_element_id=heading.element_id,
        element_ids=tuple(element.element_id for element in all_elements),
        ordinal=0,
    )
    decisions = tuple(
        ReconciliationDecision(
            decision_id=stable_identifier("decision", element.element_id),
            page_number=element.page_number,
            output_element_id=element.element_id,
            accepted_candidate_id=element.source_candidates[0].candidate_id,
            reason="fixture accepted",
            confidence=0.98,
        )
        for element in all_elements
    )
    return CanonicalDocumentV2(
        document_id=stable_document_id(CHECKSUM),
        filename="paper.pdf",
        checksum=CHECKSUM,
        page_count=2,
        pipeline=pipeline,
        pipeline_fingerprint=pipeline.fingerprint,
        pages=pages,
        sections=(section,),
        tables=tables,
        equations=equations,
        figures=figures,
        reconciliation_decisions=decisions,
        quality=DocumentQuality(status=QualityStatus.PASS, overall=0.98),
    )


def test_markdown_is_deterministic_anchored_and_derived_from_v2_json() -> None:
    document = canonical_document()
    renderer = CanonicalMarkdownRenderer()

    first = renderer.render(document)
    second = renderer.render(document)

    assert first == second
    assert first.pipeline_fingerprint == document.pipeline_fingerprint
    assert first.content_sha256 == hashlib.sha256(first.content.encode()).hexdigest()
    assert all(
        f'id="{element.element_id}"' in first.content
        for page in document.pages
        for element in page.elements
    )
    assert "| Model A | 92.4 |" in first.content
    assert "$$\nE = mc^2\n$$" in first.content
    assert "[inferred description]" in first.content


def test_semantic_chunker_emits_atomic_multimodal_chunks_with_precise_spans() -> None:
    document = canonical_document()
    chunks = SemanticChunkerV2(child_character_limit=500).chunk(
        document,
        document_id="stored-doc",
        workspace_id="ws-1",
        file_id="file-1",
    )
    children = [chunk for chunk in chunks if chunk.level == "child"]
    kinds = {chunk.content_kind for chunk in children}

    assert {"body", "table_caption", "table_cells", "table_summary", "equation", "figure"} <= kinds
    assert all(chunk.evidence_spans for chunk in chunks)
    assert all(
        span.element_id in chunk.source_block_ids
        for chunk in chunks
        for span in chunk.evidence_spans
    )
    equation = next(chunk for chunk in children if chunk.content_kind == "equation")
    assert equation.text.count("E = mc^2") == 1
    assert equation.element_types == [ElementType.EQUATION]
    assert {span.page_number for span in equation.evidence_spans} == {1, 2}
    figure = next(chunk for chunk in children if chunk.content_kind == "figure")
    assert figure.contains_inferred_content is True
    assert "inferred" in figure.text.casefold()


def test_cross_page_body_chunk_keeps_multiple_spans_without_fake_merged_bbox() -> None:
    chunks = SemanticChunkerV2(child_character_limit=1000).chunk(
        canonical_document(with_artifacts=False),
        document_id="stored-doc",
        workspace_id="ws-1",
        file_id="file-1",
    )
    body = next(
        chunk
        for chunk in chunks
        if chunk.level == "child" and chunk.content_kind == "body"
    )

    assert body.page_start == 1 and body.page_end == 2
    assert {span.page_number for span in body.evidence_spans} == {1, 2}
    assert body.bbox.model_dump() == body.evidence_spans[0].bbox.model_dump()


@pytest.mark.asyncio
async def test_v2_index_is_idempotent_and_pipeline_fingerprint_change_rebuilds(database) -> None:
    embeddings = CountingEmbeddings()
    indexer = DocumentIndexerV2(database, embeddings, embedding_model="fake-v2")
    document = canonical_document()

    first = await indexer.index("ws-1", "file-1", FILE_DATA, document)
    call_count = embeddings.calls
    second = await indexer.index("ws-1", "file-1", FILE_DATA, document)
    pipeline = document.pipeline.model_copy(update={"config": {"revision": 2}})
    changed = document.model_copy(
        update={"pipeline": pipeline, "pipeline_fingerprint": pipeline.fingerprint}
    )
    rebuilt = await indexer.index("ws-1", "file-1", FILE_DATA, changed)

    assert [chunk.chunk_id for chunk in second] == [chunk.chunk_id for chunk in first]
    assert embeddings.calls == call_count + len(rebuilt)
    assert rebuilt[0].document_id != first[0].document_id
    with database() as session:
        stored = session.query(ParsedDocumentModel).one()
        assert stored.metadata_json["pipeline_fingerprint"] == changed.pipeline_fingerprint
        assert stored.metadata_json["index_version"] == CURRENT_INDEX_VERSION
        assert stored.metadata_json["section_schema_version"] == CURRENT_SECTION_SCHEMA_VERSION


@pytest.mark.asyncio
async def test_twelve_legacy_records_are_rebuilt_as_v2_without_cross_read(database) -> None:
    document = canonical_document()
    with database() as session:
        for index in range(12):
            session.add(
                ParsedDocumentModel(
                    id=f"legacy-doc-{index:02d}",
                    workspace_id="ws-1",
                    file_id=f"legacy-file-{index:02d}",
                    checksum=CHECKSUM,
                    parser_name="pymupdf-v1",
                    parser_version="1.0",
                    page_count=2,
                    quality_score=80,
                    metadata_json={"index_version": CURRENT_INDEX_VERSION - 1},
                )
            )
        session.commit()
    indexer = DocumentIndexerV2(
        database, CountingEmbeddings(), embedding_model="fake-v2"
    )

    for index in range(12):
        await indexer.index(
            "ws-1", f"legacy-file-{index:02d}", FILE_DATA, document
        )

    with database() as session:
        stored = session.query(ParsedDocumentModel).order_by(ParsedDocumentModel.file_id).all()
        assert len(stored) == 12
        assert {item.parser_name for item in stored} == {"hybrid-document-v2"}
        assert all("canonical_document" in item.metadata_json for item in stored)
        assert session.query(ParsedDocumentModel).filter(
            ParsedDocumentModel.id.like("legacy-doc-%")
        ).count() == 0


@pytest.mark.asyncio
async def test_v2_index_rejects_checksum_mismatch_and_non_ready_document(database) -> None:
    indexer = DocumentIndexerV2(database, CountingEmbeddings(), embedding_model="fake-v2")
    document = canonical_document()
    with pytest.raises(ValueError, match="checksum"):
        await indexer.index("ws-1", "file-1", b"different", document)
    failed = document.model_copy(
        update={"quality": DocumentQuality(status=QualityStatus.FAILED, overall=0.1)}
    )
    with pytest.raises(ValueError, match="not ready"):
        await indexer.index("ws-1", "file-1", FILE_DATA, failed)


@pytest.mark.asyncio
async def test_v2_delete_is_workspace_scoped_and_invalidates_derived_ir(database) -> None:
    embeddings = CountingEmbeddings()
    indexer = DocumentIndexerV2(database, embeddings, embedding_model="fake-v2")
    document = canonical_document()
    await indexer.index("ws-1", "file-1", FILE_DATA, document)
    await indexer.index("ws-2", "file-1", FILE_DATA, document)

    indexer.delete("ws-1", "file-1")

    with database() as session:
        assert session.query(ParsedDocumentModel).filter_by(workspace_id="ws-1").count() == 0
        assert session.query(DocumentChunkModel).filter_by(workspace_id="ws-1").count() == 0
        other = session.query(ParsedDocumentModel).filter_by(workspace_id="ws-2").one()
        assert "canonical_document" in other.metadata_json
        assert "derived_markdown" in other.metadata_json


@pytest.mark.parametrize(
    ("query", "element_filter", "expected_kind"),
    [
        ("calibration benchmark", {ElementType.PARAGRAPH}, "body"),
        ("second page stable", {ElementType.PARAGRAPH}, "body"),
        ("Table 1 Calibration scores", {ElementType.TABLE}, "table_caption"),
        ("Model A", {ElementType.TABLE_CELL}, "table_cells"),
        ("92.4", {ElementType.TABLE_CELL}, "table_cells"),
        ("Row 1 Column 1", {ElementType.TABLE}, "table_summary"),
        ("E = mc^2", {ElementType.EQUATION}, "equation"),
        ("Equation 1 energy", {ElementType.EQUATION}, "equation"),
        ("Figure 1 Calibration trend", {ElementType.FIGURE}, "figure"),
        ("rising trend line", {ElementType.FIGURE}, "figure"),
        ("references Figure 1", {ElementType.FIGURE}, "figure"),
        ("Table with 1 rows", {ElementType.TABLE}, "table_summary"),
    ],
)
@pytest.mark.asyncio
async def test_twelve_question_style_multimodal_retrieval_cases(
    database,
    query: str,
    element_filter: set[ElementType] | None,
    expected_kind: str,
) -> None:
    embeddings = CountingEmbeddings()
    indexer = DocumentIndexerV2(database, embeddings, embedding_model="fake-v2")
    await indexer.index("ws-1", "file-1", FILE_DATA, canonical_document())
    retriever = HybridRetriever(database, embeddings, LexicalReranker())

    hits = await retriever.search(
        query,
        workspace_id="ws-1",
        file_ids={"file-1"},
        element_types=element_filter,
        limit=8,
    )

    assert hits
    assert hits[0].content_kind == expected_kind
    assert {hit.workspace_id for hit in hits} == {"ws-1"}
    assert all(hit.evidence_spans for hit in hits)


@pytest.mark.asyncio
async def test_element_filter_does_not_weaken_workspace_or_file_isolation(database) -> None:
    embeddings = CountingEmbeddings()
    indexer = DocumentIndexerV2(database, embeddings, embedding_model="fake-v2")
    await indexer.index("ws-1", "file-1", FILE_DATA, canonical_document())
    await indexer.index("ws-2", "file-1", FILE_DATA, canonical_document())
    retriever = HybridRetriever(database, embeddings, LexicalReranker())

    hits = await retriever.search(
        "92.4",
        workspace_id="ws-1",
        file_ids={"file-1"},
        element_types={ElementType.TABLE_CELL},
    )

    assert hits
    assert {hit.workspace_id for hit in hits} == {"ws-1"}
    assert all(ElementType.TABLE_CELL.value in hit.element_types for hit in hits)
