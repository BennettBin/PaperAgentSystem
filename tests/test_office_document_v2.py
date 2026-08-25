from __future__ import annotations

import hashlib
import io
import zipfile
from dataclasses import dataclass
from pathlib import Path

import pytest

from backend.apps.api.product_service import _hit_dict
from backend.core.errors import ErrorCode, ProjectError
from backend.document_processing.adaptive_pipeline import ProductionDocumentPipeline
from backend.document_processing.docling_adapter import (
    DoclingBoundingBox,
    DoclingCellCandidate,
    DoclingItemCandidate,
)
from backend.document_processing.office_adapter import (
    DoclingOfficeAdapter,
    OfficeBackendResult,
    OfficeEmbeddedImageCandidate,
)
from backend.document_processing.office_preflight import OfficePreflight
from backend.document_processing.schema_v2 import (
    ElementType,
    LocatorType,
    ParsingContext,
    PipelineDescriptor,
)
from backend.document_processing.vlm_contract import (
    PixelBoundingBox,
    VLMElementCandidate,
    VLMPageResponse,
    VLMResponseStatus,
)
from backend.rag.retrieval import RetrievalHit
from backend.rag.semantic_indexing_v2 import SemanticChunkerV2
from evaluation.datasets.office_parsing_v2 import office_v2_corpus


@dataclass
class ControlledOfficeBackend:
    calls: int = 0

    def convert(self, file_data: bytes, filename: str, timeout_seconds: float) -> OfficeBackendResult:
        del file_data, timeout_seconds
        self.calls += 1
        is_docx = filename.endswith(".docx")
        count = 2 if is_docx else 2
        items = tuple(
            DoclingItemCandidate(
                item_id=f"item-{number}",
                subset_page_number=number,
                label="section_header" if number == 1 else "paragraph",
                content_layer="body",
                text=f"Native office text {number}",
                bbox=DoclingBoundingBox(20, 20, 500, 80),
                reading_order=number - 1,
                hierarchy_level=0,
            )
            for number in range(1, count + 1)
        )
        return OfficeBackendResult(
            items=items,
            locator_count=count,
            locator_sizes={number: (720.0, 540.0) for number in range(1, count + 1)},
        )


def _context(data: bytes) -> ParsingContext:
    pipeline = PipelineDescriptor(router_version="office-test", render_scale=1, components=())
    return ParsingContext(
        trace_id="office-test",
        document_checksum=hashlib.sha256(data).hexdigest(),
        pipeline=pipeline,
        timeout_seconds=5,
    )


def test_bounded_office_corpus_contains_12_native_samples() -> None:
    corpus = office_v2_corpus()
    assert len(corpus) == 12
    assert {sample.filename.rsplit(".", 1)[-1] for sample in corpus} == {"docx", "pptx"}
    assert all(sample.data.startswith(b"PK") for sample in corpus)


def test_docling_optional_group_pins_office_extra() -> None:
    pyproject = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(
        encoding="utf-8"
    )
    assert "docling-slim[format-office,format-pdf,models-local]==2.115.0" in pyproject


@pytest.mark.parametrize("sample", office_v2_corpus(), ids=lambda sample: sample.case_id)
def test_office_preflight_accepts_bounded_docx_and_pptx(sample) -> None:
    result = OfficePreflight().inspect(sample.data, sample.filename, sample.content_type)
    assert result.locator_type.value == sample.locator_type
    assert result.checksum == hashlib.sha256(sample.data).hexdigest()
    assert result.native_locator_count == sample.expected_locator_count


def test_office_preflight_rejects_mime_extension_mismatch() -> None:
    sample = office_v2_corpus()[0]
    with pytest.raises(ProjectError) as exc_info:
        OfficePreflight().inspect(sample.data, "wrong.pptx", sample.content_type)
    assert exc_info.value.code is ErrorCode.UNSAFE_FILE_TYPE


def test_office_preflight_rejects_external_relationship() -> None:
    sample = office_v2_corpus()[0]
    unsafe = _rewrite_archive(
        sample.data,
        {
            "_rels/.rels": (
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="image" Target="https://example.invalid/x" '
                'TargetMode="External"/></Relationships>'
            ).encode()
        },
    )
    with pytest.raises(ProjectError) as exc_info:
        OfficePreflight().inspect(unsafe, sample.filename, sample.content_type)
    assert exc_info.value.code is ErrorCode.UNSAFE_FILE_TYPE


def test_office_preflight_rejects_archive_path_escape() -> None:
    sample = office_v2_corpus()[0]
    unsafe = _rewrite_archive(sample.data, {"../escape.xml": b"unsafe"})
    with pytest.raises(ProjectError) as exc_info:
        OfficePreflight().inspect(unsafe, sample.filename, sample.content_type)
    assert exc_info.value.code is ErrorCode.UNSAFE_FILE_TYPE


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("filename", "expected_locator"),
    [("native.docx", LocatorType.DOCX_POSITION), ("native.pptx", LocatorType.PPTX_SLIDE)],
)
async def test_docling_office_adapter_maps_locator_semantics(
    filename: str, expected_locator: LocatorType
) -> None:
    sample = next(item for item in office_v2_corpus() if item.filename.endswith(filename[-5:]))
    backend = ControlledOfficeBackend()
    document = await DoclingOfficeAdapter(backend=backend).parse(
        sample.data, filename, context=_context(sample.data)
    )
    assert backend.calls == 1
    assert document.document_locator_type is expected_locator
    assert document.page_count == 2
    assert document.quality.ready_for_index
    assert all(page.selected_route.value == "layout_native" for page in document.pages)
    assert all(
        element.provenance.parser_name == "docling-office-v2"
        for page in document.pages
        for element in page.elements
    )


@pytest.mark.asyncio
async def test_native_office_path_does_not_have_a_vlm_surface() -> None:
    sample = office_v2_corpus()[0]
    backend = ControlledOfficeBackend()
    adapter = DoclingOfficeAdapter(backend=backend)
    await adapter.parse(sample.data, sample.filename, context=_context(sample.data))
    assert backend.calls == 1
    assert not hasattr(adapter, "vlm")


@pytest.mark.asyncio
async def test_office_chunks_preserve_docx_locator_type() -> None:
    sample = office_v2_corpus()[0]
    document = await DoclingOfficeAdapter(backend=ControlledOfficeBackend()).parse(
        sample.data, sample.filename, context=_context(sample.data)
    )
    chunks = SemanticChunkerV2().chunk(
        document,
        document_id=document.document_id,
        workspace_id="workspace-a",
        file_id="file-a",
    )
    assert chunks
    assert {
        span.locator_type for chunk in chunks for span in chunk.evidence_spans
    } == {LocatorType.DOCX_POSITION}


class _PDFPipelineMustNotRun:
    async def parse_with_diagnostics(self, *args, **kwargs):
        raise AssertionError("PDF adaptive pipeline must not run for Office")


@pytest.mark.asyncio
async def test_production_pipeline_parses_office_as_canonical_v2() -> None:
    sample = office_v2_corpus()[0]
    runtime = ProductionDocumentPipeline(
        _PDFPipelineMustNotRun(),  # type: ignore[arg-type]
        office=DoclingOfficeAdapter(backend=ControlledOfficeBackend()),
    )
    outcome = await runtime.parse(
        sample.data,
        sample.filename,
        trace_id="office-production",
    )
    assert outcome.document.document_locator_type is LocatorType.DOCX_POSITION


def test_answer_evidence_exposes_office_locator_type() -> None:
    span = __import__(
        "backend.document_processing.schema_v2", fromlist=["EvidenceSpan"]
    ).EvidenceSpan(
        element_id="el_123456789012345678901234",
        page_number=2,
        locator_type=LocatorType.PPTX_SLIDE,
        bbox={"x0": 0, "y0": 0, "x1": 10, "y1": 10},
        normalized_bbox={"x0": 0, "y0": 0, "x1": 1, "y1": 1},
        source_parser="docling-office-v2",
    )
    payload = _hit_dict(
        1,
        RetrievalHit(
            chunk_id="chunk-1",
            workspace_id="workspace-a",
            file_id="file-a",
            text="slide evidence",
            section_path=("Results",),
            page_start=2,
            page_end=2,
            bbox=(0, 0, 10, 10),
            source_block_ids=(),
            score=1,
            evidence_spans=(span,),
        ),
    )
    assert payload["locator_type"] == "pptx_slide"
    assert payload["locator_label"] == "幻灯片 2"


class _ControlledOfficeVLM:
    def __init__(self) -> None:
        self.calls = 0

    async def infer(self, request, *, timeout_seconds: float) -> VLMPageResponse:
        del timeout_seconds
        self.calls += 1
        return VLMPageResponse(
            request_id=request.request_id,
            page_number=request.page_number,
            status=VLMResponseStatus.SUCCESS,
            model_name="controlled-office-vlm",
            model_version="fixture",
            elements=(
                VLMElementCandidate(
                    element_type=ElementType.PARAGRAPH,
                    text="Native office text 2",
                    original_text="Native office text 2",
                    bbox=PixelBoundingBox(x0=0, y0=0, x1=50, y1=20),
                    reading_order=0,
                    confidence=0.9,
                ),
                VLMElementCandidate(
                    element_type=ElementType.PARAGRAPH,
                    text="Scanned diagram text",
                    original_text="Scanned diagram text",
                    bbox=PixelBoundingBox(x0=0, y0=30, x1=80, y1=60),
                    reading_order=1,
                    confidence=0.91,
                ),
            ),
        )


class _OfficeBackendWithEmbeddedImage(ControlledOfficeBackend):
    def convert(self, file_data: bytes, filename: str, timeout_seconds: float) -> OfficeBackendResult:
        base = super().convert(file_data, filename, timeout_seconds)
        return OfficeBackendResult(
            items=base.items,
            locator_count=base.locator_count,
            locator_sizes=base.locator_sizes,
            embedded_images=(
                OfficeEmbeddedImageCandidate(
                    image_id="image-1",
                    locator_number=2,
                    image_bytes=b"fixture-png",
                    image_width=100,
                    image_height=100,
                    bbox=DoclingBoundingBox(20, 100, 520, 500),
                ),
            ),
        )


@pytest.mark.asyncio
async def test_embedded_image_uses_vlm_and_deduplicates_native_text() -> None:
    sample = office_v2_corpus()[0]
    provider = _ControlledOfficeVLM()
    document = await DoclingOfficeAdapter(
        backend=_OfficeBackendWithEmbeddedImage(),
        vlm_provider=provider,
    ).parse(sample.data, sample.filename, context=_context(sample.data))

    texts = [element.text for page in document.pages for element in page.elements]
    assert provider.calls == 1
    assert texts.count("Native office text 2") == 1
    assert texts.count("Scanned diagram text") == 1
    scanned = next(element for page in document.pages for element in page.elements if element.text == "Scanned diagram text")
    assert scanned.provenance.parser_name == "paddleocr-vl-office-region"


class _OfficeTableBackend:
    def convert(self, file_data: bytes, filename: str, timeout_seconds: float) -> OfficeBackendResult:
        del file_data, filename, timeout_seconds
        return OfficeBackendResult(
            items=(
                DoclingItemCandidate(
                    item_id="table-1",
                    subset_page_number=1,
                    label="table",
                    content_layer="body",
                    text="Metric Value",
                    bbox=DoclingBoundingBox(20, 20, 500, 200),
                    reading_order=0,
                    hierarchy_level=0,
                    cells=(
                        DoclingCellCandidate(0, 0, 1, 1, "Metric", DoclingBoundingBox(20, 20, 250, 100)),
                        DoclingCellCandidate(0, 1, 1, 1, "Value", DoclingBoundingBox(250, 20, 500, 100)),
                    ),
                ),
            ),
            locator_count=1,
            locator_sizes={1: (720, 540)},
        )


@pytest.mark.asyncio
async def test_office_table_cells_enter_canonical_structure() -> None:
    sample = office_v2_corpus()[0]
    document = await DoclingOfficeAdapter(backend=_OfficeTableBackend()).parse(
        sample.data, sample.filename, context=_context(sample.data)
    )
    types = [element.element_type for page in document.pages for element in page.elements]
    assert types.count(ElementType.TABLE) == 1
    assert types.count(ElementType.TABLE_CELL) == 2
    assert len(document.tables) == 1
    assert len(document.tables[0].cells) == 2


def _rewrite_archive(data: bytes, updates: dict[str, bytes]) -> bytes:
    source = zipfile.ZipFile(io.BytesIO(data))
    entries = {name: source.read(name) for name in source.namelist()}
    source.close()
    entries.update(updates)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, value in sorted(entries.items()):
            archive.writestr(name, value)
    return output.getvalue()
