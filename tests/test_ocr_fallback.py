from io import BytesIO

import fitz
import pytest

from document_processing.ocr import OCRFallbackParser, OCRLine
from document_processing.pdf_parser import PyMuPDFParser
from infrastructure.fake.observability import FakeTraceWriter


def scanned_pdf() -> bytes:
    document = fitz.open()
    page = document.new_page(width=600, height=800)
    pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 100, 100), 0)
    pixmap.clear_with(220)
    page.insert_image(page.rect, stream=pixmap.tobytes("png"))
    stream = BytesIO()
    document.save(stream)
    document.close()
    return stream.getvalue()


class FakeOCR:
    def __init__(self, name: str, confidence: float, text: str) -> None:
        self.name = name
        self.confidence = confidence
        self.text = text
        self.calls = 0

    async def recognize(self, image: bytes, page_number: int) -> list[OCRLine]:
        self.calls += 1
        return [OCRLine(self.text, self.confidence, (10, 10, 300, 40))]


@pytest.mark.asyncio
async def test_scanned_pdf_uses_ocr_and_never_silently_indexes_empty_text() -> None:
    traces = FakeTraceWriter()
    ocr = FakeOCR("fake-ocr", 0.95, "Scanned paper content")
    parser = OCRFallbackParser(
        PyMuPDFParser(),
        ocr,
        trace_writer=traces,
    )

    parsed = await parser.parse(scanned_pdf(), "scan.pdf", trace_id="trace-ocr")

    assert parsed.full_text == "Scanned paper content"
    assert parsed.quality.pages_with_text == 1
    assert parsed.parser_name.endswith("fake-ocr")
    assert traces.traces[-1]["data"]["fallback_used"] is True
    assert traces.traces[-1]["data"]["scanned_pages"] == [1]


@pytest.mark.asyncio
async def test_low_confidence_primary_falls_back_and_warns_when_needed() -> None:
    traces = FakeTraceWriter()
    primary = FakeOCR("primary", 0.1, "uncertain")
    secondary = FakeOCR("secondary", 0.9, "recovered text")
    parser = OCRFallbackParser(
        PyMuPDFParser(),
        primary,
        secondary=secondary,
        trace_writer=traces,
    )

    parsed = await parser.parse(scanned_pdf(), "scan.pdf", trace_id="trace-ocr")

    assert parsed.full_text == "recovered text"
    assert primary.calls == secondary.calls == 1
    assert parsed.quality.score == pytest.approx(0.9)
    assert traces.traces[-1]["data"]["ocr_engine"] == "secondary"


@pytest.mark.asyncio
async def test_empty_ocr_result_has_explicit_low_quality_warning() -> None:
    parser = OCRFallbackParser(
        PyMuPDFParser(),
        FakeOCR("empty", 0.0, ""),
        trace_writer=FakeTraceWriter(),
    )

    parsed = await parser.parse(scanned_pdf(), "scan.pdf", trace_id="trace-ocr")

    assert "ocr_produced_no_text" in parsed.quality.warnings
    assert "low_ocr_confidence" in parsed.quality.warnings
    assert parsed.quality.score == 0
