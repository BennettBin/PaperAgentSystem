"""PyMuPDF parser with layout-aware reading order and quality scoring."""

from __future__ import annotations

import re
from collections import Counter
from statistics import median
from typing import Any, Literal

import fitz  # type: ignore[import-untyped]

from backend.core.errors import ErrorCode, ProjectError
from backend.core.ports.processing import DocumentParser
from backend.document_processing.schema import (
    BoundingBox,
    DocumentSection,
    ParsedDocument,
    ParsedPage,
    ParseQuality,
    TextBlock,
    VisualArtifact,
)

VisualKind = Literal["figure", "table", "algorithm"]


class PyMuPDFParser(DocumentParser):
    name = "pymupdf"
    version = "1.2.0"
    VISUAL_CAPTION = re.compile(
        r"^(?P<kind>figure|fig\.?|图|table|表|algorithm|算法)\s*"
        r"(?P<number>[A-Z]?\d+(?:[.\-]\d+)*)?\s*[:.：\-]?\s*(?P<title>.*)$",
        re.IGNORECASE,
    )
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
            parsed_pages = [
                self._parse_page(page, index + 1) for index, page in enumerate(document)
            ]
        finally:
            document.close()
        pages = [item[0] for item in parsed_pages]
        artifacts = [artifact for _, page_artifacts in parsed_pages for artifact in page_artifacts]
        headers, footers = self._repeated_margins(pages)
        self._mark_margins(pages, set(headers), set(footers))
        sections = self._sections(pages)
        artifacts = self._attach_artifact_sections(artifacts, sections)
        full_text = "\n".join(
            block.text
            for page in pages
            for block in page.blocks
            if block.role not in {"header", "footer", "artifact_body"}
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
            visual_artifacts=artifacts,
        )

    def _parse_page(
        self, page: fitz.Page, page_number: int
    ) -> tuple[ParsedPage, list[VisualArtifact]]:
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
        artifacts, artifact_body_ids = self._extract_visual_artifacts(
            page, page_number, raw_blocks
        )
        for item in raw_blocks:
            item["role"] = (
                "artifact_body" if item["id"] in artifact_body_ids else "body"
            )
        column_count = self._column_count(
            raw_blocks, page.rect.width, page.rect.height
        )
        ordered = self._reading_order(
            raw_blocks, page.rect.width, page.rect.height, column_count
        )
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
                role=item["role"],
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
        parsed_page = ParsedPage(
            page_number=page_number,
            width=page.rect.width,
            height=page.rect.height,
            blocks=blocks,
            text="\n".join(block.text for block in blocks),
            image_coverage=coverage,
            layout="double_column" if column_count == 2 else "single_column",
            column_count=column_count,
        )
        return parsed_page, artifacts

    @staticmethod
    def _column_count(
        blocks: list[dict[str, Any]], page_width: float, page_height: float
    ) -> int:
        candidates = [
            block
            for block in blocks
            if block.get("role") != "artifact_body"
            and block["bbox"][1] > page_height * 0.06
            and block["bbox"][3] < page_height * 0.94
            and (block["bbox"][2] - block["bbox"][0]) <= page_width * 0.58
        ]
        midpoint = page_width / 2
        left = [
            block
            for block in candidates
            if (block["bbox"][0] + block["bbox"][2]) / 2 < midpoint * 0.92
        ]
        right = [
            block
            for block in candidates
            if (block["bbox"][0] + block["bbox"][2]) / 2 > midpoint * 1.08
        ]
        if len(left) < 2 or len(right) < 2:
            return 1
        gutter = median(item["bbox"][0] for item in right) - median(
            item["bbox"][2] for item in left
        )
        left_range = (min(item["bbox"][1] for item in left), max(item["bbox"][3] for item in left))
        right_range = (
            min(item["bbox"][1] for item in right),
            max(item["bbox"][3] for item in right),
        )
        overlap = max(
            0.0,
            min(left_range[1], right_range[1]) - max(left_range[0], right_range[0]),
        )
        shorter_height = max(
            1.0,
            min(left_range[1] - left_range[0], right_range[1] - right_range[0]),
        )
        return 2 if gutter >= page_width * 0.015 and overlap / shorter_height >= 0.35 else 1

    @staticmethod
    def _reading_order(
        blocks: list[dict[str, Any]],
        page_width: float,
        page_height: float,
        column_count: int | None = None,
    ) -> list[dict[str, Any]]:
        body = [
            block
            for block in blocks
            if block["bbox"][1] > page_height * 0.05
            and block["bbox"][3] < page_height * 0.95
        ]
        if column_count != 2:
            return sorted(blocks, key=lambda block: (block["bbox"][1], block["bbox"][0]))
        midpoint = page_width / 2
        column_blocks = [
            block
            for block in body
            if (block["bbox"][2] - block["bbox"][0]) <= page_width * 0.62
        ]
        left = [
            block
            for block in column_blocks
            if (block["bbox"][0] + block["bbox"][2]) / 2 < midpoint
        ]
        right = [block for block in column_blocks if block not in left]
        margins = [block for block in blocks if block not in body]
        spanning = [block for block in body if block not in column_blocks]
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

    def _extract_visual_artifacts(
        self,
        page: fitz.Page,
        page_number: int,
        blocks: list[dict[str, Any]],
    ) -> tuple[list[VisualArtifact], set[str]]:
        page_rect = fitz.Rect(page.rect)
        boxed_regions = self._boxed_regions(page)
        candidates: dict[str, list[fitz.Rect]] = {
            "figure": [*self._image_regions(page), *boxed_regions],
            "table": self._table_regions(page),
            "algorithm": boxed_regions,
        }
        artifacts: list[VisualArtifact] = []
        used_regions: set[tuple[int, int, int, int]] = set()
        caption_ids: set[str] = set()
        for block in blocks:
            match = self.VISUAL_CAPTION.match(block["text"].strip())
            if match is None:
                continue
            kind = self._visual_kind(match.group("kind"))
            caption = block["text"].strip()
            caption_rect = fitz.Rect(block["bbox"])
            region = self._nearest_region(caption_rect, candidates[kind], kind)
            if region is None and kind == "algorithm":
                region = self._algorithm_text_region(caption_rect, blocks)
            if region is None:
                continue
            crop = (region | caption_rect) + (-4, -4, 4, 4)
            crop &= page_rect
            key = tuple(round(value) for value in crop)
            if key in used_regions or crop.is_empty:
                continue
            used_regions.add(key)
            caption_ids.add(block["id"])
            artifacts.append(
                self._artifact(
                    page,
                    page_number,
                    len(artifacts),
                    kind,
                    self._visual_label(match, page_number),
                    caption,
                    crop,
                    blocks,
                )
            )
        for kind in ("figure", "table"):
            for region in candidates[kind]:
                if region.get_area() < page_rect.get_area() * 0.025:
                    continue
                crop = region + (-4, -4, 4, 4)
                crop &= page_rect
                if any(
                    self._overlap_ratio(crop, self._rect(item.bbox)) > 0.8
                    for item in artifacts
                ):
                    continue
                artifacts.append(
                    self._artifact(
                        page,
                        page_number,
                        len(artifacts),
                        kind,
                        f"{kind.title()} on page {page_number}",
                        "",
                        crop,
                        blocks,
                    )
                )
        body_ids = {
            block["id"]
            for artifact in artifacts
            for block in blocks
            if block["id"] not in caption_ids
            and self._overlap_ratio(fitz.Rect(block["bbox"]), self._rect(artifact.bbox)) >= 0.55
        }
        return artifacts, body_ids

    @staticmethod
    def _image_regions(page: fitz.Page) -> list[fitz.Rect]:
        return [
            fitz.Rect(info["bbox"])
            for info in page.get_image_info()
            if fitz.Rect(info["bbox"]).get_area() > 400
        ]

    @staticmethod
    def _table_regions(page: fitz.Page) -> list[fitz.Rect]:
        finder = getattr(page, "find_tables", None)
        if finder is None:
            return []
        try:
            return [fitz.Rect(table.bbox) for table in finder().tables]
        except Exception:
            return []

    @staticmethod
    def _boxed_regions(page: fitz.Page) -> list[fitz.Rect]:
        regions = []
        for drawing in page.get_drawings():
            rect = fitz.Rect(drawing["rect"])
            if rect.width >= 120 and rect.height >= 45:
                regions.append(rect)
        return regions

    @staticmethod
    def _nearest_region(
        caption: fitz.Rect, regions: list[fitz.Rect], kind: str
    ) -> fitz.Rect | None:
        if not regions:
            return None

        def distance(region: fitz.Rect) -> float:
            vertical = min(abs(caption.y0 - region.y1), abs(region.y0 - caption.y1))
            horizontal = max(0.0, max(caption.x0, region.x0) - min(caption.x1, region.x1))
            contains = -1000.0 if kind == "algorithm" and region.contains(caption) else 0.0
            return float(vertical + horizontal * 0.4 + contains)

        selected = min(regions, key=distance)
        return selected if distance(selected) <= 90 or selected.contains(caption) else None

    @staticmethod
    def _algorithm_text_region(
        caption: fitz.Rect, blocks: list[dict[str, Any]]
    ) -> fitz.Rect | None:
        following = [
            fitz.Rect(block["bbox"])
            for block in blocks
            if block["bbox"][1] >= caption.y0
            and block["bbox"][1] <= caption.y1 + 220
            and block["bbox"][0] >= caption.x0 - 20
        ]
        if len(following) < 2:
            return None
        region = fitz.Rect(caption)
        for item in following:
            region |= item
        return region

    def _artifact(
        self,
        page: fitz.Page,
        page_number: int,
        index: int,
        kind: VisualKind,
        label: str,
        caption: str,
        crop: fitz.Rect,
        blocks: list[dict[str, Any]],
    ) -> VisualArtifact:
        source_ids = [
            block["id"]
            for block in blocks
            if self._overlap_ratio(fitz.Rect(block["bbox"]), crop) >= 0.2
        ]
        pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), clip=crop, alpha=False)
        return VisualArtifact(
            artifact_id=f"p{page_number}-visual-{index + 1}",
            kind=kind,
            label=label,
            caption=caption,
            page_number=page_number,
            bbox=BoundingBox(x0=crop.x0, y0=crop.y0, x1=crop.x1, y1=crop.y1),
            source_block_ids=source_ids,
            image_png=pixmap.tobytes("png"),
        )

    @staticmethod
    def _visual_kind(value: str) -> VisualKind:
        lower = value.casefold().rstrip(".")
        if lower in {"table", "表"}:
            return "table"
        if lower in {"algorithm", "算法"}:
            return "algorithm"
        return "figure"

    @staticmethod
    def _visual_label(match: re.Match[str], page_number: int) -> str:
        kind = match.group("kind").rstrip(".")
        number = match.group("number") or ""
        return f"{kind} {number}".strip() or f"Visual on page {page_number}"

    @staticmethod
    def _overlap_ratio(left: fitz.Rect, right: fitz.Rect) -> float:
        intersection = left & right
        return (
            0.0
            if intersection.is_empty
            else float(intersection.get_area()) / max(1.0, float(left.get_area()))
        )

    @staticmethod
    def _rect(box: BoundingBox) -> fitz.Rect:
        return fitz.Rect(box.x0, box.y0, box.x1, box.y1)

    @staticmethod
    def _attach_artifact_sections(
        artifacts: list[VisualArtifact], sections: list[DocumentSection]
    ) -> list[VisualArtifact]:
        attached = []
        for artifact in artifacts:
            matching = [
                section
                for section in sections
                if section.page_start <= artifact.page_number <= section.page_end
                and bool(set(artifact.source_block_ids) & set(section.block_ids))
            ]
            if not matching:
                matching = [
                    section
                    for section in sections
                    if section.page_start <= artifact.page_number <= section.page_end
                ]
            section = matching[-1] if matching else None
            attached.append(
                artifact.model_copy(
                    update={
                        "section_id": section.section_id if section else None,
                        "section_path": list(section.section_path) if section else [],
                    }
                )
            )
        return attached

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
