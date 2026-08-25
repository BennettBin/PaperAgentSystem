from __future__ import annotations

from pathlib import Path

import pytest

from backend.core.ports.document_processing import DocumentLayoutAdapter
from backend.document_processing.adaptive_pipeline import (
    AdaptiveDocumentPipeline,
    ProductionDocumentPipeline,
)
from backend.document_processing.paddleocr_vl_adapter import PaddleOCRVLAdapter
from backend.document_processing.pymupdf_adapter import PyMuPDFV2Adapter
from backend.document_processing.schema_v2 import (
    AdapterParseResult,
    CoordinateSpace,
    PageSelection,
    ParseRoute,
    ParserProvenance,
    ParsingContext,
    QualityStatus,
)
from backend.document_processing.vlm_contract import (
    PixelBoundingBox,
    VLMElementCandidate,
    VLMPageRequest,
    VLMPageResponse,
    VLMResponseStatus,
)

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "tests" / "fixtures" / "document_parsing_v2"


class FakeLayoutAdapter(DocumentLayoutAdapter):
    name = "docling-layout-v2"
    version = "test"

    def __init__(self) -> None:
        self._native = PyMuPDFV2Adapter()
        self.calls: list[tuple[int, ...]] = []

    async def supports_format(self, filename: str) -> bool:
        return filename.endswith(".pdf")

    async def parse_pages(
        self,
        file_data: bytes,
        filename: str,
        selection: PageSelection,
        context: ParsingContext,
    ) -> AdapterParseResult:
        self.calls.append(selection.page_numbers)
        result = await self._native.parse_pages(file_data, filename, selection, context)
        pages = tuple(
            page.model_copy(
                update={
                    "elements": tuple(
                        element.model_copy(
                            update={
                                "provenance": ParserProvenance(
                                    parser_name=self.name,
                                    parser_version=self.version,
                                    confidence=element.provenance.confidence,
                                    source_coordinate_space=CoordinateSpace.PDF_POINT,
                                    is_inferred=element.is_inferred,
                                )
                            }
                        )
                        for element in page.elements
                    )
                }
            )
            for page in result.pages
        )
        return result.model_copy(
            update={"parser_name": self.name, "parser_version": self.version, "pages": pages}
        )


class FakeVLMProvider:
    async def infer(
        self, request: VLMPageRequest, *, timeout_seconds: float
    ) -> VLMPageResponse:
        del timeout_seconds
        return VLMPageResponse(
            request_id=request.request_id,
            page_number=request.page_number,
            status=VLMResponseStatus.SUCCESS,
            model_name="test-document-vlm",
            model_version="1",
            elements=(
                VLMElementCandidate(
                    element_type="paragraph",
                    text=f"VLM recognized page {request.page_number}",
                    bbox=PixelBoundingBox(
                        x0=10,
                        y0=10,
                        x1=max(20, request.image_width - 10),
                        y1=max(20, request.image_height / 3),
                    ),
                    reading_order=0,
                    confidence=0.96,
                ),
            ),
        )


def pipeline(*, vlm_enabled: bool = True) -> tuple[AdaptiveDocumentPipeline, FakeLayoutAdapter]:
    layout = FakeLayoutAdapter()
    return (
        AdaptiveDocumentPipeline(
            PyMuPDFV2Adapter(),
            layout,
            PaddleOCRVLAdapter(provider=FakeVLMProvider()),
            document_vlm_enabled=vlm_enabled,
        ),
        layout,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("filename", "route"),
    [
        ("native-single-01.pdf", ParseRoute.FAST_NATIVE),
        ("native-single-02.pdf", ParseRoute.FAST_NATIVE),
        ("native-double-01.pdf", ParseRoute.LAYOUT_NATIVE),
        ("native-double-02.pdf", ParseRoute.LAYOUT_NATIVE),
        ("table-01.pdf", ParseRoute.LAYOUT_NATIVE),
        ("formula-01.pdf", ParseRoute.LAYOUT_NATIVE),
        ("scan-01.pdf", ParseRoute.DOCUMENT_VLM),
        ("scan-02.pdf", ParseRoute.DOCUMENT_VLM),
        ("mixed-01.pdf", ParseRoute.DOCUMENT_VLM),
        ("mixed-02.pdf", ParseRoute.DOCUMENT_VLM),
        ("image-dense-01.pdf", ParseRoute.DOCUMENT_VLM),
        ("image-dense-02.pdf", ParseRoute.DOCUMENT_VLM),
    ],
)
async def test_twelve_bounded_upload_samples_take_expected_route(
    filename: str, route: ParseRoute
) -> None:
    parser, _layout = pipeline()
    data = (CORPUS / filename).read_bytes()

    outcome = await parser.parse_with_diagnostics(data, filename, trace_id=filename)

    assert outcome.diagnostics.document_route is route
    assert outcome.document.quality.ready_for_index
    assert outcome.diagnostics.pipeline_fingerprint == outcome.document.pipeline_fingerprint
    assert all(page.reasons for page in outcome.diagnostics.pages if page.route is not ParseRoute.FAST_NATIVE)


@pytest.mark.asyncio
async def test_vlm_disabled_is_explicitly_not_index_ready() -> None:
    parser, _layout = pipeline(vlm_enabled=False)
    data = (CORPUS / "scan-01.pdf").read_bytes()

    outcome = await parser.parse_with_diagnostics(data, "scan-01.pdf", trace_id="disabled")

    assert outcome.document.quality.status in {QualityStatus.RETRY_WITH_VLM, QualityStatus.FAILED}
    assert not outcome.document.quality.ready_for_index
    assert outcome.diagnostics.failed_adapter_pages == 1
    assert "document_vlm_disabled" in " ".join(outcome.diagnostics.pages[0].warnings)


@pytest.mark.asyncio
async def test_production_pipeline_returns_only_canonical_v2() -> None:
    adaptive, _layout = pipeline()
    runtime = ProductionDocumentPipeline(adaptive)
    data = (CORPUS / "native-single-01.pdf").read_bytes()

    outcome = await runtime.parse(data, "native-single-01.pdf", trace_id="v2-only")

    assert outcome.document.schema_version == "2.0"
    assert outcome.diagnostics is not None


@pytest.mark.asyncio
async def test_v2_parser_failure_is_not_hidden_by_v1_fallback() -> None:
    adaptive, _layout = pipeline(vlm_enabled=False)
    runtime = ProductionDocumentPipeline(adaptive)
    data = (CORPUS / "scan-01.pdf").read_bytes()

    outcome = await runtime.parse(data, "scan-01.pdf", trace_id="fail-closed")

    assert outcome.document.schema_version == "2.0"
    assert not outcome.document.quality.ready_for_index
