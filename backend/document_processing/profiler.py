"""Extract deterministic page signals without invoking a model."""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from typing import Any, cast

import fitz  # type: ignore[import-untyped]

from backend.document_processing.schema_v2 import (
    CanonicalBoundingBox,
    PageSignals,
    Rotation,
)

FORMULA_PATTERN = re.compile(
    r"(?:[A-Za-z][A-Za-z0-9_]*\s*=|sum_|sqrt|log\s*\(|exp\s*\(|[∑∫√±≤≥])"
)


class PageProfiler:
    def profile_document(self, file_data: bytes) -> tuple[PageSignals, ...]:
        document = fitz.open(stream=file_data, filetype="pdf")
        try:
            return tuple(
                self.profile_page(page, page_number)
                for page_number, page in enumerate(document, start=1)
            )
        finally:
            document.close()

    def profile_page(self, page: fitz.Page, page_number: int) -> PageSignals:
        page_dict = page.get_text("dict")
        text_lines = _text_lines(page_dict)
        native_text = "\n".join(line["text"] for line in text_lines)
        image_rects = [
            fitz.Rect(block["bbox"])
            for block in page_dict.get("blocks", [])
            if block.get("type") == 1 and "bbox" in block
        ]
        page_area = max(1.0, float(page.rect.width * page.rect.height))
        image_coverage = min(
            1.0,
            sum(max(0.0, rect.get_area()) for rect in image_rects) / page_area,
        )
        text_rects = [fitz.Rect(line["bbox"]) for line in text_lines]
        drawings = page.get_drawings()
        table_finder = getattr(page, "find_tables", None)
        has_tables = False
        if table_finder is not None:
            try:
                has_tables = bool(table_finder().tables)
            except Exception:
                has_tables = False
        cropbox = _box(page.cropbox)
        mediabox = _box(page.mediabox)
        return PageSignals(
            page_number=page_number,
            width=float(page.rect.width),
            height=float(page.rect.height),
            rotation=_rotation(int(page.rotation)),
            cropbox=cropbox,
            mediabox=mediabox,
            native_character_count=len("".join(native_text.split())),
            character_density=len(native_text) / page_area,
            garble_ratio=_garble_ratio(native_text),
            image_coverage=image_coverage,
            text_overlap_ratio=_overlap_ratio(text_rects),
            bbox_out_of_bounds_ratio=_out_of_bounds_ratio(text_rects, page.rect),
            detected_column_count=_column_count(text_rects, page.rect),
            has_tables=has_tables,
            has_formulas=bool(FORMULA_PATTERN.search(native_text)),
            has_drawings=bool(drawings),
            drawing_count=len(drawings),
            suspected_duplicate_ocr=_suspected_duplicate_text(text_lines),
            text_block_count=len(text_lines),
            image_block_count=len(image_rects),
        )


def _text_lines(page_dict: dict[str, Any]) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = []
    for block in page_dict.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            text = " ".join(
                str(span.get("text", "")).strip()
                for span in line.get("spans", [])
                if str(span.get("text", "")).strip()
            )
            if text and "bbox" in line:
                lines.append({"text": text, "bbox": tuple(line["bbox"])})
    return lines


def _garble_ratio(text: str) -> float:
    characters = [character for character in text if not character.isspace()]
    if not characters:
        return 0.0
    invalid = sum(
        character == "\ufffd"
        or character == "\x00"
        or unicodedata.category(character) in {"Cc", "Cs", "Co", "Cn"}
        for character in characters
    )
    return invalid / len(characters)


def _overlap_ratio(rects: list[fitz.Rect]) -> float:
    if len(rects) < 2:
        return 0.0
    overlapping: set[int] = set()
    for left_index, left in enumerate(rects):
        for right_index in range(left_index + 1, len(rects)):
            right = rects[right_index]
            intersection = left & right
            if intersection.is_empty:
                continue
            ratio = intersection.get_area() / max(
                1.0, min(left.get_area(), right.get_area())
            )
            if ratio >= 0.5:
                overlapping.update((left_index, right_index))
    return len(overlapping) / len(rects)


def _out_of_bounds_ratio(rects: list[fitz.Rect], page_rect: fitz.Rect) -> float:
    if not rects:
        return 0.0
    invalid = sum(
        rect.x0 < page_rect.x0
        or rect.y0 < page_rect.y0
        or rect.x1 > page_rect.x1
        or rect.y1 > page_rect.y1
        or not all(math.isfinite(value) for value in (rect.x0, rect.y0, rect.x1, rect.y1))
        for rect in rects
    )
    return float(invalid) / len(rects)


def _column_count(rects: list[fitz.Rect], page_rect: fitz.Rect) -> int:
    body = [
        rect
        for rect in rects
        if rect.y0 > page_rect.height * 0.05
        and rect.y1 < page_rect.height * 0.95
        and rect.width < page_rect.width * 0.65
    ]
    if len(body) < 4:
        return 1
    bins = Counter(
        min(2, max(0, int(((rect.x0 + rect.x1) / 2) / page_rect.width * 3)))
        for rect in body
    )
    occupied = [index for index, count in bins.items() if count >= 2]
    if len(occupied) >= 3:
        return 3
    if len(occupied) == 2 and max(occupied) - min(occupied) >= 1:
        return 2
    return 1


def _suspected_duplicate_text(lines: list[dict[str, Any]]) -> bool:
    normalized = [" ".join(str(line["text"]).casefold().split()) for line in lines]
    normalized = [value for value in normalized if value]
    if len(normalized) < 4:
        return False
    duplicates = sum(count - 1 for count in Counter(normalized).values() if count > 1)
    return duplicates / len(normalized) >= 0.20


def _box(rect: fitz.Rect) -> CanonicalBoundingBox:
    return CanonicalBoundingBox(
        x0=max(0.0, float(rect.x0)),
        y0=max(0.0, float(rect.y0)),
        x1=max(0.0, float(rect.x1)),
        y1=max(0.0, float(rect.y1)),
    )


def _rotation(value: int) -> Rotation:
    normalized = value % 360
    if normalized not in (0, 90, 180, 270):
        normalized = 0
    return cast(Rotation, normalized)
