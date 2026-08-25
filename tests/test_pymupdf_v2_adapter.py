from __future__ import annotations

import hashlib
import inspect
from io import BytesIO
from pathlib import Path

import fitz
import pytest

from backend.core.errors import ErrorCode, ProjectError
from backend.document_processing.pymupdf_adapter import PyMuPDFV2Adapter
from backend.document_processing.schema_v2 import (
    CoordinateSpace,
    ElementType,
    PageSelection,
    ParsingContext,
    PipelineComponent,
    PipelineDescriptor,
    normalize_element_text,
)

ROOT = Path(__file__).resolve().parents[1]
CORPUS_ROOT = ROOT / "tests" / "fixtures" / "document_parsing_v2"


def context(data: bytes) -> ParsingContext:
    pipeline = PipelineDescriptor(
        router_version="router-v1",
        render_scale=2,
        components=(
            PipelineComponent(name=PyMuPDFV2Adapter.name, version=PyMuPDFV2Adapter.version),
        ),
    )
    return ParsingContext(
        trace_id="trace-pymupdf-v2",
        document_checksum=hashlib.sha256(data).hexdigest(),
        pipeline=pipeline,
        timeout_seconds=30,
    )


def repeated_margin_pdf() -> bytes:
    document = fitz.open()
    for page_number in range(1, 3):
        page = document.new_page(width=600, height=800)
        page.insert_text((40, 25), "Repeated Journal Header", fontsize=8)
        page.insert_text((40, 90), f"{page_number} Section", fontsize=16)
        page.insert_text((40, 130), f"Page-specific evidence {page_number}", fontsize=11)
        page.insert_text((270, 780), f"Page {page_number}", fontsize=8)
    stream = BytesIO()
    document.save(stream, no_new_id=True)
    document.close()
    return stream.getvalue()


@pytest.mark.asyncio
async def test_adapter_preserves_block_line_span_hierarchy_and_provenance() -> None:
    data = (CORPUS_ROOT / "native-single-01.pdf").read_bytes()
    result = await PyMuPDFV2Adapter().parse_pages(
        data,
        "native-single-01.pdf",
        PageSelection(page_numbers=(1,)),
        context(data),
    )

    page = result.pages[0]
    by_id = {element.element_id: element for element in page.elements}
    roots = [element for element in page.elements if element.parent_id is None]
    lines = [element for element in page.elements if element.element_type is ElementType.TEXT_LINE]
    spans = [element for element in page.elements if element.element_type is ElementType.TEXT_SPAN]

    assert roots and lines and spans
    assert all(by_id[child].parent_id == root.element_id for root in roots for child in root.children_ids)
    assert all(element.provenance.parser_name == PyMuPDFV2Adapter.name for element in page.elements)
    assert all(element.provenance.source_coordinate_space is CoordinateSpace.PDF_POINT for element in page.elements)
    assert all(0 <= element.normalized_bbox.x0 <= element.normalized_bbox.x1 <= 1 for element in page.elements)
    assert all(0 <= element.normalized_bbox.y0 <= element.normalized_bbox.y1 <= 1 for element in page.elements)


@pytest.mark.asyncio
async def test_adapter_marks_only_repeated_margins_as_headers_and_footers() -> None:
    data = repeated_margin_pdf()
    result = await PyMuPDFV2Adapter().parse_pages(
        data,
        "margins.pdf",
        PageSelection(page_numbers=(1, 2)),
        context(data),
    )
    roots = [
        element
        for page in result.pages
        for element in page.elements
        if element.parent_id is None
    ]

    assert sum(element.element_type is ElementType.PAGE_HEADER for element in roots) == 2
    assert sum(element.element_type is ElementType.PAGE_FOOTER for element in roots) == 2
    assert all(
        element.element_type is not ElementType.PAGE_HEADER
        for element in roots
        if "Section" in element.text
    )


@pytest.mark.asyncio
async def test_single_page_top_title_is_not_removed_as_header() -> None:
    data = (CORPUS_ROOT / "native-single-01.pdf").read_bytes()
    result = await PyMuPDFV2Adapter().parse_pages(
        data,
        "native-single-01.pdf",
        PageSelection(page_numbers=(1,)),
        context(data),
    )

    roots = [element for element in result.pages[0].elements if element.parent_id is None]
    assert all(element.element_type is not ElementType.PAGE_HEADER for element in roots)
    assert any("PaperAgent Parsing Corpus" in element.text for element in roots)


@pytest.mark.asyncio
@pytest.mark.parametrize("filename", ["rotated-01.pdf", "rotated-crop.pdf"])
async def test_adapter_outputs_visible_page_coordinates_for_rotation_and_cropbox(
    filename: str,
) -> None:
    data = (CORPUS_ROOT / filename).read_bytes()
    result = await PyMuPDFV2Adapter().parse_pages(
        data,
        filename,
        PageSelection(page_numbers=(1,)),
        context(data),
    )
    page = result.pages[0]

    assert page.elements
    assert all(0 <= item.bbox.x0 <= item.bbox.x1 <= page.width for item in page.elements)
    assert all(0 <= item.bbox.y0 <= item.bbox.y1 <= page.height for item in page.elements)
    if filename == "rotated-01.pdf":
        assert page.rotation == 90
        assert (page.width, page.height) == (792, 612)
    else:
        assert page.rotation == 0
        assert (page.width, page.height) == (570, 726)


@pytest.mark.asyncio
async def test_adapter_honors_page_selection_and_rejects_invalid_selection() -> None:
    data = (CORPUS_ROOT / "mixed-01.pdf").read_bytes()
    adapter = PyMuPDFV2Adapter()
    selected = await adapter.parse_pages(
        data,
        "mixed-01.pdf",
        PageSelection(page_numbers=(2,)),
        context(data),
    )

    assert [page.page_number for page in selected.pages] == [2]
    with pytest.raises(ProjectError) as captured:
        await adapter.parse_pages(
            data,
            "mixed-01.pdf",
            PageSelection(page_numbers=(3,)),
            context(data),
        )
    assert captured.value.code is ErrorCode.OUT_OF_RANGE


@pytest.mark.asyncio
async def test_adapter_rejects_checksum_mismatch() -> None:
    data = (CORPUS_ROOT / "native-single-01.pdf").read_bytes()
    invalid = context(data).model_copy(update={"document_checksum": "0" * 64})

    with pytest.raises(ProjectError) as captured:
        await PyMuPDFV2Adapter().parse_pages(
            data,
            "native-single-01.pdf",
            PageSelection(page_numbers=(1,)),
            invalid,
        )
    assert captured.value.code is ErrorCode.FAILED_PRECONDITION
    assert captured.value.details["reason"] == "document_checksum_mismatch"


def test_text_normalization_preserves_original_separately_and_repairs_ligature_hyphen() -> None:
    original = "A ﬁne inter-\noperable result"

    assert normalize_element_text(original) == "A fine interoperable result"
    assert original == "A ﬁne inter-\noperable result"


def test_fast_adapter_has_no_gpu_or_document_vlm_dependency() -> None:
    source = inspect.getsource(PyMuPDFV2Adapter)

    assert "torch" not in source
    assert "paddle" not in source.casefold()
    assert "docling" not in source.casefold()
