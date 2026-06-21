"""PyMuPDF parser with layout-aware reading order and quality scoring."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

import fitz  # type: ignore[import-untyped]

from core.errors import ErrorCode, ProjectError
from core.ports.processing import DocumentParser
from document_processing.schema import (
    BoundingBox,
    DocumentSection,
    ParsedDocument,
    ParsedPage,
    ParseQuality,
    TextBlock,
)


class PyMuPDFParser(DocumentParser):
    name = "pymupdf"
    version = "1.0.0"
    HEADING_PATTERN = re.compile(
        r"^(?:\d+(?:\.\d+)*\s+|abstract$|introduction$|methods?$|results?$|"
        r"discussion$|conclusion$|references$)",
        re.IGNORECASE,
    )

    async def supports_format(self, filename: str) -> bool:
        return filename.lower().endswith(".pdf")

    async def parse(self, file_data: bytes, filename: str) -> ParsedDocument:
        if not await self.supports_format(filename):
            raise ProjectError(ErrorCode.PARSING_FAILED, "PyMuPDF parser requires a PDF")
        try:
            document = fitz.open(stream=file_data, filetype="pdf")
        except Exception as exc:
            raise ProjectError(ErrorCode.PARSING_FAILED, "Invalid PDF document", cause=exc) from exc
        try:
            pages = [self._parse_page(page, index + 1) for index, page in enumerate(document)]
        finally:
            document.close()
        headers, footers = self._repeated_margins(pages)
        self._mark_margins(pages, set(headers), set(footers))
        sections = self._sections(pages)
        full_text = "\n".join(
            block.text
            for page in pages
            for block in page.blocks
            if block.role not in {"header", "footer"}
        )
        return ParsedDocument(
            filename=filename,
            page_count=len(pages),
            pages=pages,
            sections=sections,
            headers=headers,
            footers=footers,
            full_text=full_text,
            quality=self._quality(pages, full_text),
            parser_name=self.name,
            parser_version=self.version,
        )

    def _parse_page(self, page: fitz.Page, page_number: int) -> ParsedPage:
        raw_blocks: list[dict[str, Any]] = []
        page_dict = page.get_text("dict")
        sequence = 0
        for raw in page_dict.get("blocks", []):
            if raw.get("type") != 0:
                continue
            for line in raw.get("lines", []):
                text_parts, sizes = [], []
                for span in line.get("spans", []):
                    text_parts.append(str(span.get("text", "")))
                    sizes.append(float(span.get("size", 0)))
                text = " ".join(part.strip() for part in text_parts if part.strip()).strip()
                if text:
                    raw_blocks.append(
                        {
                            "id": f"p{page_number}-b{sequence}",
                            "text": text,
                            "bbox": tuple(float(value) for value in line["bbox"]),
                            "font_size": max(sizes, default=0.0),
                        }
                    )
                    sequence += 1
        ordered = self._reading_order(raw_blocks, page.rect.width, page.rect.height)
        blocks = [
            TextBlock(
                block_id=item["id"],
                page_number=page_number,
                text=item["text"],
                bbox=BoundingBox(
                    x0=item["bbox"][0],
                    y0=item["bbox"][1],
                    x1=item["bbox"][2],
                    y1=item["bbox"][3],
                ),
                font_size=item["font_size"],
                reading_order=index,
            )
            for index, item in enumerate(ordered)
        ]
        image_area = sum(
            max(0.0, raw["bbox"][2] - raw["bbox"][0])
            * max(0.0, raw["bbox"][3] - raw["bbox"][1])
            for raw in page_dict.get("blocks", [])
            if raw.get("type") == 1
        )
        coverage = min(1.0, image_area / max(1.0, page.rect.width * page.rect.height))
        return ParsedPage(
            page_number=page_number,
            width=page.rect.width,
            height=page.rect.height,
            blocks=blocks,
            text="\n".join(block.text for block in blocks),
            image_coverage=coverage,
        )

    @staticmethod
    def _reading_order(
        blocks: list[dict[str, Any]],
        page_width: float,
        page_height: float,
    ) -> list[dict[str, Any]]:
        body = [
            block
            for block in blocks
            if block["bbox"][1] > page_height * 0.05
            and block["bbox"][3] < page_height * 0.95
        ]
        left = [block for block in body if block["bbox"][2] <= page_width * 0.58]
        right = [block for block in body if block["bbox"][0] >= page_width * 0.42]
        two_columns = len(left) >= 2 and len(right) >= 2
        if not two_columns:
            return sorted(blocks, key=lambda block: (block["bbox"][1], block["bbox"][0]))
        margins = [block for block in blocks if block not in body]
        spanning = [block for block in body if block not in left and block not in right]
        first_column_y = min(item["bbox"][1] for item in left + right)
        top = [block for block in spanning if block["bbox"][1] < first_column_y]
        remaining = [block for block in spanning if block not in top]
        return [
            *sorted([block for block in margins if block["bbox"][1] <= page_height * 0.05], key=lambda item: item["bbox"][0]),
            *sorted(top, key=lambda block: (block["bbox"][1], block["bbox"][0])),
            *sorted(left, key=lambda block: (block["bbox"][1], block["bbox"][0])),
            *sorted(right, key=lambda block: (block["bbox"][1], block["bbox"][0])),
            *sorted(remaining, key=lambda block: (block["bbox"][1], block["bbox"][0])),
            *sorted([block for block in margins if block["bbox"][1] > page_height * 0.05], key=lambda item: item["bbox"][0]),
        ]

    @staticmethod
    def _repeated_margins(pages: list[ParsedPage]) -> tuple[list[str], list[str]]:
        threshold = max(2, (len(pages) + 1) // 2)
        headers = Counter(
            block.text
            for page in pages
            for block in page.blocks
            if block.bbox.y0 <= page.height * 0.05
        )
        footers = Counter(
            block.text
            for page in pages
            for block in page.blocks
            if block.bbox.y1 >= page.height * 0.95
        )
        return (
            sorted(text for text, count in headers.items() if count >= threshold),
            sorted(
                text
                for text, count in footers.items()
                if count >= threshold or text.lower().startswith("page ")
            ),
        )

    @staticmethod
    def _mark_margins(
        pages: list[ParsedPage],
        headers: set[str],
        footers: set[str],
    ) -> None:
        for page in pages:
            for block in page.blocks:
                if block.text in headers or block.bbox.y0 <= page.height * 0.05:
                    block.role = "header"
                elif block.text in footers or block.bbox.y1 >= page.height * 0.95:
                    block.role = "footer"

    def _sections(self, pages: list[ParsedPage]) -> list[DocumentSection]:
        body_sizes = [
            block.font_size
            for page in pages
            for block in page.blocks
            if block.role == "body" and block.font_size > 0
        ]
        baseline = sorted(body_sizes)[len(body_sizes) // 2] if body_sizes else 10
        headings = [
            block
            for page in pages
            for block in page.blocks
            if block.role == "body"
            and (
                block.font_size >= baseline * 1.25
                or bool(self.HEADING_PATTERN.match(block.text.strip()))
            )
            and len(block.text) <= 160
        ]
        all_body = [
            block for page in pages for block in page.blocks if block.role == "body"
        ]
        sections = []
        for index, heading in enumerate(headings):
            next_heading = headings[index + 1] if index + 1 < len(headings) else None
            block_ids = [
                block.block_id
                for block in all_body
                if (block.page_number, block.reading_order)
                >= (heading.page_number, heading.reading_order)
                and (
                    next_heading is None
                    or (block.page_number, block.reading_order)
                    < (next_heading.page_number, next_heading.reading_order)
                )
            ]
            sections.append(
                DocumentSection(
                    section_id=f"section-{index + 1}",
                    title=heading.text,
                    level=(
                        max(1, heading.text.split()[0].count(".") + 1)
                        if heading.text[:1].isdigit()
                        else 1
                    ),
                    page_start=heading.page_number,
                    page_end=next_heading.page_number if next_heading else pages[-1].page_number,
                    block_ids=block_ids,
                )
            )
        return sections

    @staticmethod
    def _quality(pages: list[ParsedPage], full_text: str) -> ParseQuality:
        page_count = len(pages)
        pages_with_text = sum(bool(page.text.strip()) for page in pages)
        empty_ratio = 1 - pages_with_text / max(1, page_count)
        density = min(1.0, len(full_text) / max(1, page_count * 100))
        score = max(0.0, min(1.0, density * 0.7 + (1 - empty_ratio) * 0.3))
        warnings = []
        if empty_ratio > 0:
            warnings.append("one_or_more_pages_have_no_extracted_text")
        if score < 0.6:
            warnings.append("low_text_extraction_quality")
        return ParseQuality(
            score=score,
            character_count=len(full_text),
            pages_with_text=pages_with_text,
            empty_page_ratio=empty_ratio,
            warnings=warnings,
        )
