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
    version = "1.1.0"
    NUMBERED_HEADING = re.compile(
        r"^(?:(?:chapter|section)\s+)?"
        r"(?P<number>\d+(?:\.\d+)*|[A-Z](?:\.\d+)*|[IVXLC]+)"
        r"[\s.:\-]+(?P<title>[^.].{1,158})$",
        re.IGNORECASE,
    )
    APPENDIX_HEADING = re.compile(
        r"^appendix\s+(?P<number>[A-Z](?:\.\d+)*)[\s.:\-]+"
        r"(?P<title>.{2,150})$",
        re.IGNORECASE,
    )
    COMMON_SECTION_TITLES = {
        "abstract",
        "摘要",
        "introduction",
        "引言",
        "related work",
        "literature review",
        "相关工作",
        "background",
        "背景",
        "method",
        "methods",
        "methodology",
        "materials and methods",
        "方法",
        "experiments",
        "experimental setup",
        "实验",
        "results",
        "findings",
        "结果",
        "discussion",
        "讨论",
        "conclusion",
        "conclusions",
        "结论",
        "references",
        "参考文献",
        "appendix",
        "supplementary material",
        "附录",
    }

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
                text_parts, sizes, fonts, flags = [], [], [], []
                for span in line.get("spans", []):
                    text_parts.append(str(span.get("text", "")))
                    sizes.append(float(span.get("size", 0)))
                    fonts.append(str(span.get("font", "")))
                    flags.append(int(span.get("flags", 0)))
                text = " ".join(part.strip() for part in text_parts if part.strip()).strip()
                if text:
                    raw_blocks.append(
                        {
                            "id": f"p{page_number}-b{sequence}",
                            "text": text,
                            "bbox": tuple(float(value) for value in line["bbox"]),
                            "font_size": max(sizes, default=0.0),
                            "font_name": max(fonts, key=len, default=""),
                            "is_bold": any(flag & 16 for flag in flags)
                            or any("bold" in font.casefold() for font in fonts),
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
                font_name=item["font_name"],
                is_bold=item["is_bold"],
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
        toc_pages = self._toc_pages(pages)
        all_body = [
            block for page in pages for block in page.blocks if block.role == "body"
        ]
        candidates = [
            (block, *self._heading_parts(block.text))
            for block in all_body
            if block.page_number not in toc_pages
            and self._is_heading(block, baseline)
        ]
        heading_ids = {block.block_id for block, _, _, _ in candidates}
        sections: list[DocumentSection] = []
        stack: list[DocumentSection] = []
        positions = {
            block.block_id: index for index, block in enumerate(all_body)
        }
        for ordinal, (heading, number, title, level) in enumerate(candidates):
            while stack and stack[-1].level >= level:
                stack.pop()
            parent = stack[-1] if stack else None
            section_id = f"section-{ordinal + 1}"
            display_title = heading.text.strip()
            path = [
                *(parent.section_path if parent else []),
                display_title,
            ]
            start_index = positions[heading.block_id] + 1
            next_index = (
                positions[candidates[ordinal + 1][0].block_id]
                if ordinal + 1 < len(candidates)
                else len(all_body)
            )
            direct_ids = [
                block.block_id
                for block in all_body[start_index:next_index]
                if block.block_id not in heading_ids
            ]
            scope_end = len(all_body)
            for later_heading, _, _, later_level in candidates[ordinal + 1 :]:
                if later_level <= level:
                    scope_end = positions[later_heading.block_id]
                    break
            scope_blocks = all_body[start_index:scope_end]
            page_end = max(
                [heading.page_number, *(block.page_number for block in scope_blocks)]
            )
            section = DocumentSection(
                section_id=section_id,
                number=number,
                title=display_title,
                normalized_title=self._normalize_title(title),
                level=level,
                parent_section_id=parent.section_id if parent else None,
                section_path=path,
                page_start=heading.page_number,
                page_end=page_end,
                heading_block_id=heading.block_id,
                block_ids=direct_ids,
                ordinal=ordinal,
            )
            sections.append(section)
            stack.append(section)
        descendants: dict[str, list[str]] = {section.section_id: [] for section in sections}
        for section in reversed(sections):
            parent_id = section.parent_section_id
            if parent_id:
                descendants[parent_id].extend(
                    [*section.block_ids, *descendants[section.section_id]]
                )
        return [
            section.model_copy(
                update={"descendant_block_ids": descendants[section.section_id]}
            )
            for section in sections
        ]

    @classmethod
    def _is_heading(cls, block: TextBlock, baseline: float) -> bool:
        text = block.text.strip()
        if not text or len(text) > 160:
            return False
        lower = cls._normalize_title(text)
        if lower.startswith(("figure ", "fig. ", "table ")):
            return False
        if re.match(r"^\d+\s+\w+\s+et\s+al\.", text, re.IGNORECASE):
            return False
        if text.endswith(".") and lower not in cls.COMMON_SECTION_TITLES:
            return False
        number, title, _ = cls._heading_parts(text)
        structured = number is not None or lower in cls.COMMON_SECTION_TITLES
        visual = block.font_size >= baseline * 1.22 or (
            block.is_bold and block.font_size >= baseline
        )
        return structured or visual and len(title.split()) <= 14

    @classmethod
    def _heading_parts(cls, text: str) -> tuple[str | None, str, int]:
        clean = " ".join(text.strip().split())
        appendix = cls.APPENDIX_HEADING.match(clean)
        match = appendix or cls.NUMBERED_HEADING.match(clean)
        if match:
            number = match.group("number").upper()
            title = match.group("title").strip(" .:-")
            return number, title, max(1, number.count(".") + 1)
        return None, clean, 1

    @staticmethod
    def _normalize_title(title: str) -> str:
        clean = re.sub(
            r"^(?:appendix\s+)?(?:\d+(?:\.\d+)*|[A-Z](?:\.\d+)*|[IVXLC]+)"
            r"[\s.:\-]+",
            "",
            title.strip(),
            flags=re.IGNORECASE,
        )
        return " ".join(
            re.sub(r"[^\w\u4e00-\u9fff]+", " ", clean.casefold()).split()
        )

    @staticmethod
    def _toc_pages(pages: list[ParsedPage]) -> set[int]:
        result = set()
        dotted_entry = re.compile(r".{2,}\s*\d+\s*$")
        for page in pages:
            text_values = [block.text.strip().casefold() for block in page.blocks]
            has_title = any(
                value in {"contents", "table of contents", "目录"}
                for value in text_values
            )
            entries = sum(bool(dotted_entry.search(value)) for value in text_values)
            if has_title and entries >= 2:
                result.add(page.page_number)
        return result

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
