"""Fail-closed PDF preflight before parser or model dispatch."""

from __future__ import annotations

import hashlib
from typing import cast

import fitz  # type: ignore[import-untyped]

from backend.core.errors import ErrorCode, ProjectError
from backend.document_processing.config import DocumentProcessingConfig
from backend.document_processing.schema_v2 import (
    CanonicalBoundingBox,
    DocumentPreflight,
    PreflightPage,
    Rotation,
)
from backend.security.file_validation import validate_untrusted_file


class PDFPreflight:
    def __init__(self, config: DocumentProcessingConfig | None = None) -> None:
        self._config = config or DocumentProcessingConfig()

    def inspect(self, file_data: bytes, filename: str) -> DocumentPreflight:
        if not filename.casefold().endswith(".pdf"):
            raise ProjectError(
                ErrorCode.UNSAFE_FILE_TYPE,
                "Hybrid PDF preflight requires a .pdf filename",
            )
        validate_untrusted_file(
            filename,
            "application/pdf",
            file_data,
            max_bytes=self._config.max_file_bytes,
        )
        try:
            document = fitz.open(stream=file_data, filetype="pdf")
        except Exception as exc:
            raise ProjectError(
                ErrorCode.PARSING_FAILED,
                "Invalid or corrupted PDF document",
                cause=exc,
            ) from exc
        try:
            if document.needs_pass:
                raise ProjectError(
                    ErrorCode.FAILED_PRECONDITION,
                    "Encrypted PDF requires a password and cannot be parsed",
                    details={"reason": "encrypted_pdf"},
                )
            if document.page_count < 1:
                raise ProjectError(
                    ErrorCode.PARSING_FAILED,
                    "PDF document contains no pages",
                )
            if document.page_count > self._config.max_pages:
                raise ProjectError(
                    ErrorCode.RESOURCE_EXHAUSTED,
                    "PDF page count exceeds the configured limit",
                    details={
                        "page_count": document.page_count,
                        "max_pages": self._config.max_pages,
                    },
                )
            pages = tuple(
                self._inspect_page(page, page_number)
                for page_number, page in enumerate(document, start=1)
            )
            total_pixels = sum(page.estimated_render_pixels for page in pages)
            if total_pixels > self._config.max_render_pixels_per_document:
                raise ProjectError(
                    ErrorCode.RESOURCE_EXHAUSTED,
                    "PDF render pixel budget exceeds the configured document limit",
                    details={
                        "estimated_pixels": total_pixels,
                        "max_pixels": self._config.max_render_pixels_per_document,
                    },
                )
            return DocumentPreflight(
                filename=filename,
                checksum=hashlib.sha256(file_data).hexdigest(),
                detected_format="pdf",
                file_size_bytes=len(file_data),
                page_count=document.page_count,
                encrypted=False,
                pages=pages,
                total_estimated_render_pixels=total_pixels,
            )
        finally:
            document.close()

    def _inspect_page(self, page: fitz.Page, page_number: int) -> PreflightPage:
        width = float(page.rect.width)
        height = float(page.rect.height)
        if (
            width > self._config.max_page_width_points
            or height > self._config.max_page_height_points
        ):
            raise ProjectError(
                ErrorCode.RESOURCE_EXHAUSTED,
                "PDF page dimensions exceed the configured limit",
                details={
                    "page_number": page_number,
                    "width": width,
                    "height": height,
                },
            )
        estimated_pixels = max(
            1,
            int(round(width * self._config.render_scale))
            * int(round(height * self._config.render_scale)),
        )
        if estimated_pixels > self._config.max_render_pixels_per_page:
            raise ProjectError(
                ErrorCode.RESOURCE_EXHAUSTED,
                "PDF page render pixel budget exceeds the configured limit",
                details={
                    "page_number": page_number,
                    "estimated_pixels": estimated_pixels,
                    "max_pixels": self._config.max_render_pixels_per_page,
                },
            )
        return PreflightPage(
            page_number=page_number,
            width=width,
            height=height,
            rotation=_rotation(int(page.rotation)),
            cropbox=_box(page.cropbox),
            mediabox=_box(page.mediabox),
            estimated_render_pixels=estimated_pixels,
        )


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
