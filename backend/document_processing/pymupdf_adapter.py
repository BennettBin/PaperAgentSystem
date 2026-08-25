"""PyMuPDF native-text candidate Adapter for the hybrid V2 pipeline."""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from dataclasses import dataclass
from statistics import median
from typing import Any

import fitz  # type: ignore[import-untyped]

from backend.core.errors import ErrorCode, ProjectError
from backend.core.ports.document_processing import PageParserAdapter
from backend.document_processing.config import DocumentProcessingConfig
from backend.document_processing.coordinates import CoordinateTransformer
from backend.document_processing.profiler import PageProfiler
from backend.document_processing.router import DeterministicParseRouter
from backend.document_processing.schema_v2 import (
    AdapterParseResult,
    CanonicalBoundingBox,
    CanonicalPage,
    CoordinateSpace,
    DocumentElement,
    ElementType,
    PageQuality,
    PageSelection,
    ParseRoute,
    ParserProvenance,
    ParsingContext,
    QualityStatus,
    normalize_element_text,
    stable_element_id,
)

HEADING_PATTERN = re.compile(
    r"^(?:\d+(?:\.\d+)*[.)]?\s+|[A-Z][.)]\s+|"
    r"abstract$|introduction$|methods?$|results?$|discussion$|conclusions?$|references$|"
    r"摘要$|引言$|方法$|结果$|讨论$|结论$|参考文献$)",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class _RawSpan:
    text: str
    bbox: tuple[float, float, float, float]
    font: str
    size: float
    flags: int


@dataclass(frozen=True, slots=True)
class _RawLine:
    text: str
    bbox: tuple[float, float, float, float]
    spans: tuple[_RawSpan, ...]


@dataclass(frozen=True, slots=True)
class _RawBlock:
    page_number: int
    text: str
    bbox: tuple[float, float, float, float]
    lines: tuple[_RawLine, ...]


class PyMuPDFV2Adapter(PageParserAdapter):
    name = "pymupdf-native-v2"
    version = "2.0.0"

    def __init__(
        self,
        config: DocumentProcessingConfig | None = None,
        *,
        profiler: PageProfiler | None = None,
        router: DeterministicParseRouter | None = None,
    ) -> None:
        self._config = config or DocumentProcessingConfig()
        self._profiler = profiler or PageProfiler()
        self._router = router or DeterministicParseRouter(self._config)

    async def supports_format(self, filename: str) -> bool:
        return filename.casefold().endswith(".pdf")

    async def parse_pages(
        self,
        file_data: bytes,
        filename: str,
        selection: PageSelection,
        context: ParsingContext,
    ) -> AdapterParseResult:
        if not await self.supports_format(filename):
            raise ProjectError(
                ErrorCode.PARSING_FAILED,
                "PyMuPDF V2 Adapter requires a PDF",
            )
        checksum = hashlib.sha256(file_data).hexdigest()
        if checksum != context.document_checksum:
            raise ProjectError(
                ErrorCode.FAILED_PRECONDITION,
                "Parser context checksum does not match PDF bytes",
                details={"reason": "document_checksum_mismatch"},
            )
        try:
            document = fitz.open(stream=file_data, filetype="pdf")
        except Exception as exc:
            raise ProjectError(
                ErrorCode.PARSING_FAILED,
                "Invalid PDF document",
                cause=exc,
            ) from exc
        try:
            if any(page > document.page_count for page in selection.page_numbers):
                raise ProjectError(
                    ErrorCode.OUT_OF_RANGE,
                    "Selected PDF page is outside the document",
                )
            raw_by_page = {
                page_number: _raw_blocks(document[page_number - 1], page_number)
                for page_number in selection.page_numbers
            }
            headers, footers = _repeated_margins(raw_by_page, document)
            pages = tuple(
                self._parse_page(
                    document[page_number - 1],
                    page_number,
                    checksum,
                    raw_by_page[page_number],
                    headers,
                    footers,
                )
                for page_number in selection.page_numbers
            )
            return AdapterParseResult(
                parser_name=self.name,
                parser_version=self.version,
                selection=selection,
                pages=pages,
            )
        finally:
            document.close()

    def _parse_page(
        self,
        page: fitz.Page,
        page_number: int,
        checksum: str,
        raw_blocks: tuple[_RawBlock, ...],
        headers: set[str],
        footers: set[str],
    ) -> CanonicalPage:
        transformer = CoordinateTransformer.from_page(
            page,
            render_scale=self._config.render_scale,
        )
        signals = self._profiler.profile_page(page, page_number)
        profile = self._router.profile(signals)
        body_sizes = [span.size for block in raw_blocks for line in block.lines for span in line.spans]
        body_size = median(body_sizes) if body_sizes else 0.0
        elements: list[DocumentElement] = []
        reading_order = 0
        for block_index, block in enumerate(raw_blocks):
            block_box = transformer.native_to_canonical(block.bbox)
            role = _block_type(block, body_size, block_index, headers, footers)
            block_id = stable_element_id(
                checksum,
                page_number,
                role,
                reading_order,
                block_box,
                block.text,
            )
            line_ids: list[str] = []
            line_models: list[DocumentElement] = []
            span_models: list[DocumentElement] = []
            block_order = reading_order
            reading_order += 1
            for line in block.lines:
                line_box = transformer.native_to_canonical(line.bbox)
                line_id = stable_element_id(
                    checksum,
                    page_number,
                    ElementType.TEXT_LINE,
                    reading_order,
                    line_box,
                    line.text,
                )
                line_ids.append(line_id)
                line_order = reading_order
                reading_order += 1
                span_ids: list[str] = []
                for span in line.spans:
                    span_box = transformer.native_to_canonical(span.bbox)
                    span_id = stable_element_id(
                        checksum,
                        page_number,
                        ElementType.TEXT_SPAN,
                        reading_order,
                        span_box,
                        span.text,
                    )
                    span_ids.append(span_id)
                    span_models.append(
                        _element(
                            element_id=span_id,
                            page_number=page_number,
                            element_type=ElementType.TEXT_SPAN,
                            text=span.text,
                            bbox=span_box,
                            transformer=transformer,
                            reading_order=reading_order,
                            parent_id=line_id,
                            metadata={
                                "font": span.font,
                                "font_size": round(span.size, 4),
                                "font_flags": span.flags,
                                "is_bold": bool(span.flags & 16)
                                or "bold" in span.font.casefold(),
                                "language": _language(span.text),
                            },
                        )
                    )
                    reading_order += 1
                line_models.append(
                    _element(
                        element_id=line_id,
                        page_number=page_number,
                        element_type=ElementType.TEXT_LINE,
                        text=line.text,
                        bbox=line_box,
                        transformer=transformer,
                        reading_order=line_order,
                        parent_id=block_id,
                        children_ids=tuple(span_ids),
                        metadata={"language": _language(line.text)},
                    )
                )
            elements.append(
                _element(
                    element_id=block_id,
                    page_number=page_number,
                    element_type=role,
                    text=block.text,
                    bbox=block_box,
                    transformer=transformer,
                    reading_order=block_order,
                    children_ids=tuple(line_ids),
                    metadata={
                        "language": _language(block.text),
                        "source_block_index": block_index,
                    },
                )
            )
            elements.extend(line_models)
            elements.extend(span_models)
        elements.extend(
            _image_elements(page, page_number, checksum, transformer, reading_order)
        )
        coordinate_score = 1.0 - signals.bbox_out_of_bounds_ratio
        text_score = min(1.0, signals.native_character_count / max(1, self._config.native_min_characters_per_page))
        status = (
            QualityStatus.PASS
            if profile.proposed_route is ParseRoute.FAST_NATIVE
            else QualityStatus.PASS_WITH_WARNINGS
        )
        warnings = () if status is QualityStatus.PASS else profile.route_reasons
        return CanonicalPage(
            page_number=page_number,
            width=transformer.page_width,
            height=transformer.page_height,
            rotation=transformer.rotation,
            cropbox=CanonicalBoundingBox(
                x0=0,
                y0=0,
                x1=transformer.page_width,
                y1=transformer.page_height,
            ),
            selected_route=profile.proposed_route,
            route_reasons=profile.route_reasons,
            profile=profile,
            elements=tuple(sorted(elements, key=lambda item: item.reading_order)),
            quality=PageQuality(
                status=status,
                overall=(text_score + coordinate_score) / 2,
                text=text_score,
                coordinates=coordinate_score,
                reading_order=1.0 if profile.proposed_route is ParseRoute.FAST_NATIVE else 0.6,
                structure=1.0 if profile.proposed_route is ParseRoute.FAST_NATIVE else 0.6,
                ocr=1.0 if signals.image_block_count == 0 else 0.5,
                tables=1.0 if not signals.has_tables else 0.5,
                completeness=text_score,
                warnings=warnings,
            ),
        )


def _raw_blocks(page: fitz.Page, page_number: int) -> tuple[_RawBlock, ...]:
    page_dict = page.get_text("dict", sort=True)
    blocks: list[_RawBlock] = []
    for raw_block in page_dict.get("blocks", []):
        if raw_block.get("type") != 0:
            continue
        lines: list[_RawLine] = []
        for raw_line in raw_block.get("lines", []):
            spans = tuple(
                _RawSpan(
                    text=str(span.get("text", "")),
                    bbox=_bbox4(span["bbox"]),
                    font=str(span.get("font", "")),
                    size=float(span.get("size", 0)),
                    flags=int(span.get("flags", 0)),
                )
                for span in raw_line.get("spans", [])
                if str(span.get("text", ""))
            )
            text = "".join(span.text for span in spans).strip()
            if not text or not spans:
                continue
            lines.append(
                _RawLine(
                    text=text,
                    bbox=_bbox4(raw_line["bbox"]),
                    spans=spans,
                )
            )
        if not lines:
            continue
        blocks.append(
            _RawBlock(
                page_number=page_number,
                text="\n".join(line.text for line in lines),
                bbox=_bbox4(raw_block["bbox"]),
                lines=tuple(lines),
            )
        )
    return tuple(blocks)


def _bbox4(values: Any) -> tuple[float, float, float, float]:
    """Convert a PyMuPDF bbox-like value into the canonical four-value shape."""

    rectangle = fitz.Rect(values)
    return (rectangle.x0, rectangle.y0, rectangle.x1, rectangle.y1)


def _repeated_margins(
    raw_by_page: dict[int, tuple[_RawBlock, ...]],
    document: fitz.Document,
) -> tuple[set[str], set[str]]:
    if len(raw_by_page) < 2:
        return set(), set()
    header_counts: Counter[str] = Counter()
    footer_counts: Counter[str] = Counter()
    for page_number, blocks in raw_by_page.items():
        page = document[page_number - 1]
        page_headers = {
            _margin_key(block.text)
            for block in blocks
            if block.bbox[1] <= page.cropbox.height * 0.08
        }
        page_footers = {
            _margin_key(block.text)
            for block in blocks
            if block.bbox[3] >= page.cropbox.height * 0.92
        }
        header_counts.update(value for value in page_headers if value)
        footer_counts.update(value for value in page_footers if value)
    threshold = max(2, math.ceil(len(raw_by_page) * 0.5))
    return (
        {text for text, count in header_counts.items() if count >= threshold},
        {text for text, count in footer_counts.items() if count >= threshold},
    )


def _block_type(
    block: _RawBlock,
    body_size: float,
    block_index: int,
    headers: set[str],
    footers: set[str],
) -> ElementType:
    margin_key = _margin_key(block.text)
    if margin_key in headers:
        return ElementType.PAGE_HEADER
    if margin_key in footers:
        return ElementType.PAGE_FOOTER
    spans = [span for line in block.lines for span in line.spans]
    maximum_size = max((span.size for span in spans), default=0.0)
    bold = any(span.flags & 16 or "bold" in span.font.casefold() for span in spans)
    compact = normalize_element_text(block.text)
    heading = (
        len(block.lines) <= 2
        and len(compact) <= 180
        and (
            bool(HEADING_PATTERN.match(compact))
            or bold
            or (body_size > 0 and maximum_size >= body_size * 1.25)
        )
    )
    if heading and block_index == 0 and maximum_size >= max(14.0, body_size * 1.45):
        return ElementType.TITLE
    if heading:
        return ElementType.SECTION_HEADING
    return ElementType.PARAGRAPH


def _element(
    *,
    element_id: str,
    page_number: int,
    element_type: ElementType,
    text: str,
    bbox: CanonicalBoundingBox,
    transformer: CoordinateTransformer,
    reading_order: int,
    parent_id: str | None = None,
    children_ids: tuple[str, ...] = (),
    metadata: dict[str, str | int | float | bool | None] | None = None,
) -> DocumentElement:
    return DocumentElement(
        element_id=element_id,
        page_number=page_number,
        element_type=element_type,
        text=text,
        normalized_text=normalize_element_text(text),
        bbox=bbox,
        normalized_bbox=transformer.normalize(bbox),
        reading_order=reading_order,
        provenance=ParserProvenance(
            parser_name=PyMuPDFV2Adapter.name,
            parser_version=PyMuPDFV2Adapter.version,
            confidence=1.0,
            source_coordinate_space=CoordinateSpace.PDF_POINT,
        ),
        parent_id=parent_id,
        children_ids=children_ids,
        metadata=metadata or {},
    )


def _image_elements(
    page: fitz.Page,
    page_number: int,
    checksum: str,
    transformer: CoordinateTransformer,
    start_order: int,
) -> list[DocumentElement]:
    result: list[DocumentElement] = []
    for index, image in enumerate(page.get_text("dict").get("blocks", [])):
        if image.get("type") != 1 or "bbox" not in image:
            continue
        bbox = transformer.native_to_canonical(image["bbox"])
        element_id = stable_element_id(
            checksum,
            page_number,
            ElementType.FIGURE,
            start_order + len(result),
            bbox,
            f"image-{index}",
        )
        result.append(
            _element(
                element_id=element_id,
                page_number=page_number,
                element_type=ElementType.FIGURE,
                text="",
                bbox=bbox,
                transformer=transformer,
                reading_order=start_order + len(result),
                metadata={
                    "source_block_index": index,
                    "image_width": int(image.get("width", 0)),
                    "image_height": int(image.get("height", 0)),
                },
            )
        )
    return result


def _margin_key(text: str) -> str:
    normalized = normalize_element_text(text).casefold()
    return re.sub(r"\d+", "#", normalized)


def _language(text: str) -> str:
    chinese = sum("\u4e00" <= character <= "\u9fff" for character in text)
    latin = sum(character.isascii() and character.isalpha() for character in text)
    if chinese > latin:
        return "zh"
    if latin:
        return "en"
    return "und"
