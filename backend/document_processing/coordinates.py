"""Coordinate conversions for visible rotated PDF pages and rendered images."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, cast

import fitz  # type: ignore[import-untyped]

from backend.document_processing.schema_v2 import (
    CanonicalBoundingBox,
    NormalizedBoundingBox,
    Rotation,
)

MatrixTuple = tuple[float, float, float, float, float, float]


@dataclass(frozen=True, slots=True)
class CoordinateTransformer:
    """Convert all parser coordinates to the visible, rotated page coordinate space."""

    page_width: float
    page_height: float
    native_width: float
    native_height: float
    rotation: Rotation
    render_scale: float
    rotation_matrix: MatrixTuple
    derotation_matrix: MatrixTuple

    @classmethod
    def from_page(
        cls,
        page: fitz.Page,
        *,
        render_scale: float,
    ) -> "CoordinateTransformer":
        if render_scale <= 0:
            raise ValueError("render scale must be positive")
        rotation = int(page.rotation) % 360
        if rotation not in (0, 90, 180, 270):
            raise ValueError("PDF page rotation must be a multiple of 90 degrees")
        return cls(
            page_width=float(page.rect.width),
            page_height=float(page.rect.height),
            native_width=float(page.cropbox.width),
            native_height=float(page.cropbox.height),
            rotation=cast(Rotation, rotation),
            render_scale=render_scale,
            rotation_matrix=_matrix_tuple(page.rotation_matrix),
            derotation_matrix=_matrix_tuple(page.derotation_matrix),
        )

    def native_to_canonical(
        self, bbox: CanonicalBoundingBox | Iterable[float]
    ) -> CanonicalBoundingBox:
        rect = _rect(bbox) * fitz.Matrix(*self.rotation_matrix)
        return _bounded_box(rect, self.page_width, self.page_height)

    def canonical_to_native(
        self, bbox: CanonicalBoundingBox | Iterable[float]
    ) -> CanonicalBoundingBox:
        rect = _rect(bbox) * fitz.Matrix(*self.derotation_matrix)
        return _bounded_box(rect, self.native_width, self.native_height)

    def render_pixels_to_canonical(
        self, bbox: CanonicalBoundingBox | Iterable[float]
    ) -> CanonicalBoundingBox:
        rect = _rect(bbox)
        scaled = fitz.Rect(
            rect.x0 / self.render_scale,
            rect.y0 / self.render_scale,
            rect.x1 / self.render_scale,
            rect.y1 / self.render_scale,
        )
        return _bounded_box(scaled, self.page_width, self.page_height)

    def canonical_to_render_pixels(
        self, bbox: CanonicalBoundingBox | Iterable[float]
    ) -> CanonicalBoundingBox:
        rect = _rect(bbox)
        return CanonicalBoundingBox(
            x0=max(0.0, rect.x0 * self.render_scale),
            y0=max(0.0, rect.y0 * self.render_scale),
            x1=min(self.page_width, rect.x1) * self.render_scale,
            y1=min(self.page_height, rect.y1) * self.render_scale,
        )

    def normalize(
        self, bbox: CanonicalBoundingBox | Iterable[float]
    ) -> NormalizedBoundingBox:
        box = _bounded_box(_rect(bbox), self.page_width, self.page_height)
        return NormalizedBoundingBox(
            x0=box.x0 / self.page_width,
            y0=box.y0 / self.page_height,
            x1=box.x1 / self.page_width,
            y1=box.y1 / self.page_height,
        )

    def denormalize(self, bbox: NormalizedBoundingBox) -> CanonicalBoundingBox:
        return CanonicalBoundingBox(
            x0=bbox.x0 * self.page_width,
            y0=bbox.y0 * self.page_height,
            x1=bbox.x1 * self.page_width,
            y1=bbox.y1 * self.page_height,
        )


def _matrix_tuple(matrix: fitz.Matrix) -> MatrixTuple:
    return (
        float(matrix.a),
        float(matrix.b),
        float(matrix.c),
        float(matrix.d),
        float(matrix.e),
        float(matrix.f),
    )


def _rect(value: CanonicalBoundingBox | Iterable[float]) -> fitz.Rect:
    if isinstance(value, CanonicalBoundingBox):
        return fitz.Rect(value.x0, value.y0, value.x1, value.y1)
    coordinates = tuple(float(item) for item in value)
    if len(coordinates) != 4:
        raise ValueError("bbox requires exactly four coordinates")
    return fitz.Rect(*coordinates)


def _bounded_box(rect: fitz.Rect, width: float, height: float) -> CanonicalBoundingBox:
    x0 = min(width, max(0.0, float(rect.x0)))
    y0 = min(height, max(0.0, float(rect.y0)))
    x1 = min(width, max(x0, float(rect.x1)))
    y1 = min(height, max(y0, float(rect.y1)))
    return CanonicalBoundingBox(x0=x0, y0=y0, x1=x1, y1=y1)
