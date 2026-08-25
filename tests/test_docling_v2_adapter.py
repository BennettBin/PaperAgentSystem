from __future__ import annotations

import hashlib
import inspect
import json
import time
import tomllib
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path

import fitz
import pytest

from backend.document_processing.docling_adapter import (
    DoclingBackendResult,
    DoclingBoundingBox,
    DoclingCellCandidate,
    DoclingItemCandidate,
    DoclingLayoutAdapter,
    LocalDoclingBackend,
    parse_docling_candidates,
)
from backend.document_processing.schema_v2 import (
    DocumentRoutePlan,
    ElementType,
    PageSelection,
    ParseRoute,
    ParsingContext,
    PipelineComponent,
    PipelineDescriptor,
    RouteDecision,
)

ROOT = Path(__file__).resolve().parents[1]
CORPUS_ROOT = ROOT / "tests" / "fixtures" / "document_parsing_v2"
COMPLEX_SAMPLE_FILENAMES = (
    "native-double-01.pdf",
    "native-double-02.pdf",
    "native-double-03.pdf",
    "table-01.pdf",
    "table-02.pdf",
    "table-03.pdf",
    "formula-01.pdf",
    "formula-02.pdf",
    "rotated-01.pdf",
    "rotated-crop.pdf",
)


def _pdf(page_count: int = 4) -> bytes:
    document = fitz.open()
    for page_number in range(1, page_count + 1):
        page = document.new_page(width=600, height=800)
        page.insert_text((40, 80), f"Original page {page_number}")
    stream = BytesIO()
    document.save(stream, no_new_id=True)
    document.close()
    return stream.getvalue()


def _context(data: bytes, *, timeout_seconds: float = 2) -> ParsingContext:
    return ParsingContext(
        trace_id="trace-docling-v2",
        document_checksum=hashlib.sha256(data).hexdigest(),
        pipeline=PipelineDescriptor(
            router_version="router-v1",
            render_scale=2,
            components=(
                PipelineComponent(
                    name=DoclingLayoutAdapter.name,
                    version=DoclingLayoutAdapter.version,
                    model_name=DoclingLayoutAdapter.model_name,
                    model_version=DoclingLayoutAdapter.model_version,
                ),
            ),
        ),
        timeout_seconds=timeout_seconds,
    )


@dataclass
class FakeDoclingBackend:
    result: DoclingBackendResult
    calls: int = 0
    subset_page_counts: list[int] = field(default_factory=list)

    def convert(
        self, subset_pdf: bytes, filename: str, timeout_seconds: float
    ) -> DoclingBackendResult:
        del filename, timeout_seconds
        self.calls += 1
        with fitz.open(stream=subset_pdf, filetype="pdf") as document:
            self.subset_page_counts.append(document.page_count)
        return self.result


class FailingDoclingBackend:
    def __init__(self, error: Exception) -> None:
        self.error = error
        self.calls = 0

    def convert(
        self, subset_pdf: bytes, filename: str, timeout_seconds: float
    ) -> DoclingBackendResult:
        del subset_pdf, filename, timeout_seconds
        self.calls += 1
        raise self.error


class SlowDoclingBackend:
    def __init__(self) -> None:
        self.calls = 0

    def convert(
        self, subset_pdf: bytes, filename: str, timeout_seconds: float
    ) -> DoclingBackendResult:
        del subset_pdf, filename, timeout_seconds
        self.calls += 1
        time.sleep(0.05)
        return DoclingBackendResult(items=())


def _layout_result() -> DoclingBackendResult:
    return DoclingBackendResult(
        items=(
            DoclingItemCandidate(
                item_id="#/texts/0",
                subset_page_number=1,
                label="section_header",
                content_layer="body",
                text="2 Methods",
                bbox=DoclingBoundingBox(left=40, top=60, right=300, bottom=90),
                reading_order=0,
                hierarchy_level=1,
                confidence=0.98,
            ),
            DoclingItemCandidate(
                item_id="#/texts/1",
                parent_item_id="#/texts/0",
                subset_page_number=1,
                label="paragraph",
                content_layer="body",
                text="Left column before right column.",
                bbox=DoclingBoundingBox(left=40, top=110, right=280, bottom=180),
                reading_order=1,
                hierarchy_level=2,
                confidence=0.96,
            ),
            DoclingItemCandidate(
                item_id="#/tables/0",
                subset_page_number=1,
                label="table",
                content_layer="body",
                text="Model Score",
                bbox=DoclingBoundingBox(
                    left=40,
                    top=500,
                    right=560,
                    bottom=700,
                    coordinate_origin="bottom_left",
                ),
                reading_order=2,
                hierarchy_level=1,
                confidence=0.94,
                cells=(
                    DoclingCellCandidate(
                        row_index=0,
                        column_index=0,
                        row_span=1,
                        column_span=1,
                        text="Model",
                        bbox=DoclingBoundingBox(left=40, top=180, right=250, bottom=220),
                        confidence=0.93,
                    ),
                    DoclingCellCandidate(
                        row_index=0,
                        column_index=1,
                        row_span=1,
                        column_span=1,
                        text="Score",
                        bbox=DoclingBoundingBox(left=250, top=180, right=560, bottom=220),
                        confidence=0.92,
                    ),
                ),
            ),
            DoclingItemCandidate(
                item_id="#/texts/2",
                subset_page_number=1,
                label="page_footer",
                content_layer="furniture",
                text="2",
                bbox=DoclingBoundingBox(left=290, top=760, right=310, bottom=785),
                reading_order=3,
                hierarchy_level=0,
            ),
            DoclingItemCandidate(
                item_id="#/texts/3",
                subset_page_number=2,
                label="formula",
                content_layer="body",
                text="E = mc^2",
                bbox=DoclingBoundingBox(left=100, top=200, right=300, bottom=240),
                reading_order=0,
                hierarchy_level=1,
                confidence=0.91,
            ),
            DoclingItemCandidate(
                item_id="#/pictures/0",
                subset_page_number=2,
                label="picture",
                content_layer="body",
                text="",
                bbox=DoclingBoundingBox(left=80, top=300, right=500, bottom=650),
                reading_order=1,
                hierarchy_level=1,
                confidence=0.89,
            ),
        ),
        page_warnings={2: ("low_formula_confidence",)},
    )


@pytest.mark.asyncio
async def test_non_contiguous_pages_are_subsetting_and_mapped_back_to_original_pages() -> None:
    data = _pdf()
    backend = FakeDoclingBackend(_layout_result())
    result = await DoclingLayoutAdapter(backend=backend).parse_pages(
        data,
        "complex.pdf",
        PageSelection(page_numbers=(2, 4)),
        _context(data),
    )

    assert backend.calls == 1
    assert backend.subset_page_counts == [2]
    assert result.selection.original_page_map == {1: 2, 2: 4}
    assert [page.page_number for page in result.pages] == [2, 4]
    assert result.failed_pages == ()


@pytest.mark.asyncio
async def test_adapter_maps_reading_order_content_layers_labels_and_hierarchy() -> None:
    data = _pdf()
    result = await DoclingLayoutAdapter(
        backend=FakeDoclingBackend(_layout_result())
    ).parse_pages(
        data,
        "complex.pdf",
        PageSelection(page_numbers=(2, 4)),
        _context(data),
    )
    first = result.pages[0]
    roots = [element for element in first.elements if element.parent_id is None]
    heading = next(element for element in roots if element.element_type is ElementType.SECTION_HEADING)
    paragraph = next(
        element for element in first.elements if element.element_type is ElementType.PARAGRAPH
    )

    assert paragraph.parent_id == heading.element_id
    assert paragraph.element_id in heading.children_ids
    assert [item.reading_order for item in first.elements] == list(range(len(first.elements)))
    assert paragraph.metadata["content_layer"] == "body"
    assert paragraph.metadata["hierarchy_level"] == 2
    assert any(item.element_type is ElementType.PAGE_FOOTER for item in roots)
    assert all(item.is_inferred for item in first.elements)


@pytest.mark.asyncio
async def test_adapter_maps_table_cells_formula_picture_coordinates_and_model_provenance() -> None:
    data = _pdf()
    result = await DoclingLayoutAdapter(
        backend=FakeDoclingBackend(_layout_result())
    ).parse_pages(
        data,
        "complex.pdf",
        PageSelection(page_numbers=(2, 4)),
        _context(data),
    )
    first, second = result.pages
    table = next(item for item in first.elements if item.element_type is ElementType.TABLE)
    cells = [item for item in first.elements if item.element_type is ElementType.TABLE_CELL]

    assert len(cells) == 2
    assert set(table.children_ids) >= {cell.element_id for cell in cells}
    assert all(cell.parent_id == table.element_id for cell in cells)
    assert {cell.metadata["row_index"] for cell in cells} == {0}
    assert table.bbox.y0 == pytest.approx(100)
    assert table.bbox.y1 == pytest.approx(300)
    assert {item.element_type for item in second.elements} >= {
        ElementType.EQUATION,
        ElementType.FIGURE,
    }
    assert result.model_name == DoclingLayoutAdapter.model_name
    assert result.model_version == DoclingLayoutAdapter.model_version
    assert result.duration_ms >= 0
    assert all(
        item.provenance.model_version == DoclingLayoutAdapter.model_version
        for page in result.pages
        for item in page.elements
    )
    assert "low_formula_confidence" in second.quality.warnings


@pytest.mark.asyncio
async def test_partial_failure_returns_successful_pages_and_original_failed_page_numbers() -> None:
    data = _pdf()
    partial = _layout_result()
    partial = DoclingBackendResult(
        items=tuple(item for item in partial.items if item.subset_page_number == 1),
        failed_subset_pages=(2,),
        page_warnings={2: ("layout_model_failed",)},
    )
    result = await DoclingLayoutAdapter(
        backend=FakeDoclingBackend(partial)
    ).parse_pages(
        data,
        "complex.pdf",
        PageSelection(page_numbers=(2, 4)),
        _context(data),
    )

    assert [page.page_number for page in result.pages] == [2]
    assert result.failed_pages == (4,)
    assert "page_4:layout_model_failed" in result.warnings


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("backend", "expected_warning"),
    [
        (FailingDoclingBackend(ModuleNotFoundError("docling")), "docling_dependency_unavailable"),
        (FailingDoclingBackend(RuntimeError("model init failed")), "docling_model_initialization_failed"),
        (SlowDoclingBackend(), "docling_timeout"),
    ],
)
async def test_missing_dependency_timeout_and_initialization_failure_have_deterministic_fallback(
    backend: object,
    expected_warning: str,
) -> None:
    data = _pdf(2)
    timeout = 0.001 if isinstance(backend, SlowDoclingBackend) else 2
    result = await DoclingLayoutAdapter(backend=backend).parse_pages(  # type: ignore[arg-type]
        data,
        "complex.pdf",
        PageSelection(page_numbers=(1, 2)),
        _context(data, timeout_seconds=timeout),
    )

    assert result.pages == ()
    assert result.failed_pages == (1, 2)
    assert expected_warning in result.warnings


@pytest.mark.asyncio
async def test_fast_route_does_not_invoke_docling() -> None:
    data = _pdf(2)
    backend = FakeDoclingBackend(_layout_result())
    plan = DocumentRoutePlan(
        document_route=ParseRoute.FAST_NATIVE,
        decisions=(
            RouteDecision(page_number=1, route=ParseRoute.FAST_NATIVE, reasons=("native_text_clean",)),
            RouteDecision(page_number=2, route=ParseRoute.FAST_NATIVE, reasons=("native_text_clean",)),
        ),
        vlm_page_count=0,
        vlm_page_limit=10,
    )

    result = await parse_docling_candidates(
        DoclingLayoutAdapter(backend=backend),
        data,
        "fast.pdf",
        plan,
        _context(data),
    )

    assert result is None
    assert backend.calls == 0


def test_optional_dependency_versions_are_pinned_after_compatibility_spike() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert project["project"]["optional-dependencies"]["document-layout"] == [
        "docling-slim[format-office,format-pdf,models-local]==2.115.0",
        "docling-core==2.90.0",
        "docling-parse==7.10.0",
        "docling-ibm-models==3.13.0",
    ]


def test_local_backend_is_fail_closed_for_network_plugins_and_enrichment() -> None:
    source = inspect.getsource(LocalDoclingBackend)

    assert "enable_remote_services=False" in source
    assert "allow_external_plugins=False" in source
    assert "do_ocr=False" in source
    assert "do_picture_description=False" in source
    assert "do_code_enrichment=False" in source
    assert "do_formula_enrichment=False" in source


def test_v04_reuses_ten_bounded_complex_native_samples() -> None:
    manifest = json.loads((CORPUS_ROOT / "manifest.json").read_text(encoding="utf-8"))
    complex_samples = [
        sample for sample in manifest["samples"] if sample["expected_route"] == "layout_native"
    ]

    assert len(complex_samples) == 10
    assert {sample["category"] for sample in complex_samples} == {
        "native_double",
        "table_dense",
        "formula_dense",
        "rotated",
        "cropbox",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("filename", COMPLEX_SAMPLE_FILENAMES)
async def test_bounded_complex_pdf_samples_satisfy_layout_candidate_contract(
    filename: str,
) -> None:
    data = (CORPUS_ROOT / filename).read_bytes()
    backend = FakeDoclingBackend(
        DoclingBackendResult(
            items=(
                DoclingItemCandidate(
                    item_id="#/texts/0",
                    subset_page_number=1,
                    label="paragraph",
                    content_layer="body",
                    text=f"layout candidate for {filename}",
                    bbox=DoclingBoundingBox(left=10, top=10, right=100, bottom=100),
                    reading_order=0,
                    hierarchy_level=1,
                ),
            )
        )
    )

    result = await DoclingLayoutAdapter(backend=backend).parse_pages(
        data,
        filename,
        PageSelection(page_numbers=(1,)),
        _context(data),
    )

    assert backend.calls == 1
    assert len(result.pages) == 1
    assert result.pages[0].selected_route is ParseRoute.LAYOUT_NATIVE
    assert result.pages[0].elements[0].provenance.parser_name == DoclingLayoutAdapter.name
    assert result.pages[0].elements[0].bbox.x1 <= result.pages[0].width
    assert result.pages[0].elements[0].bbox.y1 <= result.pages[0].height
