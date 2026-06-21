"""OCR adapters and traceable fallback for scanned PDFs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import fitz  # type: ignore[import-untyped]

from core.errors import ErrorCode, ProjectError
from core.ports.observability import TraceWriter
from document_processing.pdf_parser import PyMuPDFParser
from document_processing.schema import (
    BoundingBox,
    ParsedDocument,
    ParsedPage,
    ParseQuality,
    TextBlock,
)


@dataclass(frozen=True, slots=True)
class OCRLine:
    text: str
    confidence: float
    bbox: tuple[float, float, float, float]


class OCREngine(Protocol):
    name: str

    async def recognize(self, image: bytes, page_number: int) -> list[OCRLine]: ...


class PaddleOCRAdapter:
    name = "paddleocr"

    def __init__(self, engine: Any | None = None) -> None:
        if engine is None:
            try:
                from paddleocr import PaddleOCR  # type: ignore[import-not-found]
            except ImportError as exc:
                raise ProjectError(
                    ErrorCode.UNAVAILABLE,
                    "PaddleOCR is not installed",
                    cause=exc,
                ) from exc
            engine = PaddleOCR(use_doc_orientation_classify=False, lang="ch")
        self._engine = engine

    async def recognize(self, image: bytes, page_number: int) -> list[OCRLine]:
        results = self._engine.predict(image)
        lines = []
        for result in results:
            payload = result.json if hasattr(result, "json") else result
            for text, score, box in zip(
                payload.get("rec_texts", []),
                payload.get("rec_scores", []),
                payload.get("rec_boxes", []),
            ):
                values = [float(value) for value in box]
                if len(values) != 4:
                    continue
                lines.append(
                    OCRLine(
                        str(text),
                        float(score),
                        (values[0], values[1], values[2], values[3]),
                    )
                )
        return lines


class TesseractOCRAdapter:
    name = "tesseract"

    def __init__(self, engine: Any | None = None) -> None:
        if engine is None:
            try:
                import pytesseract  # type: ignore[import-not-found]
            except ImportError as exc:
                raise ProjectError(
                    ErrorCode.UNAVAILABLE,
                    "Tesseract adapter dependencies are not installed",
                    cause=exc,
                ) from exc
            engine = pytesseract
        self._engine = engine

    async def recognize(self, image: bytes, page_number: int) -> list[OCRLine]:
        data = self._engine.image_to_data(
            image,
            output_type=self._engine.Output.DICT,
        )
        lines = []
        for index, text in enumerate(data["text"]):
            if not str(text).strip():
                continue
            confidence = max(0.0, float(data["conf"][index]) / 100)
            x, y = float(data["left"][index]), float(data["top"][index])
            width, height = float(data["width"][index]), float(data["height"][index])
            lines.append(OCRLine(str(text), confidence, (x, y, x + width, y + height)))
        return lines


class OCRFallbackParser:
    def __init__(
        self,
        base_parser: PyMuPDFParser,
        primary: OCREngine,
        *,
        secondary: OCREngine | None = None,
        trace_writer: TraceWriter,
        minimum_characters_per_page: int = 20,
        minimum_confidence: float = 0.55,
    ) -> None:
        self._base = base_parser
        self._primary = primary
        self._secondary = secondary
        self._traces = trace_writer
        self._minimum_chars = minimum_characters_per_page
        self._minimum_confidence = minimum_confidence

    async def parse(
        self,
        file_data: bytes,
        filename: str,
        *,
        trace_id: str,
    ) -> ParsedDocument:
        parsed = await self._base.parse(file_data, filename)
        scanned_pages = [
            page.page_number
            for page in parsed.pages
            if len(page.text.strip()) < self._minimum_chars
        ]
        if not scanned_pages:
            await self._trace(trace_id, filename, [], None, parsed.quality.score)
            return parsed
        document = fitz.open(stream=file_data, filetype="pdf")
        engines = [self._primary, *([self._secondary] if self._secondary else [])]
        selected_engine = None
        ocr_pages: dict[int, ParsedPage] = {}
        confidences = []
        try:
            for engine in engines:
                if engine is None:
                    continue
                trial_pages: dict[int, ParsedPage] = {}
                trial_confidences: list[float] = []
                for page_number in scanned_pages:
                    page = document[page_number - 1]
                    image = page.get_pixmap(matrix=fitz.Matrix(2, 2)).tobytes("png")
                    lines = await engine.recognize(image, page_number)
                    trial_confidences.extend(line.confidence for line in lines)
                    trial_pages[page_number] = self._ocr_page(
                        page_number,
                        page.rect.width,
                        page.rect.height,
                        lines,
                    )
                mean = (
                    sum(trial_confidences) / len(trial_confidences)
                    if trial_confidences
                    else 0.0
                )
                if mean >= self._minimum_confidence or engine is engines[-1]:
                    selected_engine = engine.name
                    ocr_pages = trial_pages
                    confidences = trial_confidences
                    break
        finally:
            document.close()
        for index, page in enumerate(parsed.pages):
            if page.page_number in ocr_pages:
                parsed.pages[index] = ocr_pages[page.page_number]
        parsed.full_text = "\n".join(page.text for page in parsed.pages)
        mean_confidence = sum(confidences) / len(confidences) if confidences else 0.0
        warnings = list(parsed.quality.warnings)
        if not parsed.full_text.strip():
            warnings.append("ocr_produced_no_text")
        if mean_confidence < self._minimum_confidence:
            warnings.append("low_ocr_confidence")
        parsed.quality = ParseQuality(
            score=min(1.0, mean_confidence),
            character_count=len(parsed.full_text),
            pages_with_text=sum(bool(page.text.strip()) for page in parsed.pages),
            empty_page_ratio=sum(not page.text.strip() for page in parsed.pages)
            / max(1, len(parsed.pages)),
            warnings=list(dict.fromkeys(warnings)),
        )
        parsed.parser_name = f"{parsed.parser_name}+{selected_engine or 'ocr_failed'}"
        await self._trace(
            trace_id,
            filename,
            scanned_pages,
            selected_engine,
            parsed.quality.score,
        )
        return parsed

    @staticmethod
    def _ocr_page(
        page_number: int,
        width: float,
        height: float,
        lines: list[OCRLine],
    ) -> ParsedPage:
        ordered = sorted(lines, key=lambda line: (line.bbox[1], line.bbox[0]))
        blocks = [
            TextBlock(
                block_id=f"p{page_number}-ocr-{index}",
                page_number=page_number,
                text=line.text,
                bbox=BoundingBox(
                    x0=line.bbox[0],
                    y0=line.bbox[1],
                    x1=line.bbox[2],
                    y1=line.bbox[3],
                ),
                font_size=0,
                role="body",
                reading_order=index,
            )
            for index, line in enumerate(ordered)
        ]
        return ParsedPage(
            page_number=page_number,
            width=width,
            height=height,
            blocks=blocks,
            text="\n".join(block.text for block in blocks),
            image_coverage=1.0,
        )

    async def _trace(
        self,
        trace_id: str,
        filename: str,
        scanned_pages: list[int],
        engine: str | None,
        quality: float,
    ) -> None:
        await self._traces.write_trace(
            trace_id,
            "document.ocr_fallback",
            {
                "filename": filename,
                "scanned_pages": scanned_pages,
                "ocr_engine": engine,
                "quality_score": quality,
                "fallback_used": bool(scanned_pages),
            },
        )
