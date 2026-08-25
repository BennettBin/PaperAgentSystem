from __future__ import annotations

from io import BytesIO

import fitz
import pytest

from backend.document_processing.coordinates import CoordinateTransformer
from backend.document_processing.schema_v2 import CanonicalBoundingBox


def page_with_rotation(rotation: int) -> tuple[fitz.Document, fitz.Page]:
    document = fitz.open()
    page = document.new_page(width=600, height=800)
    page.set_rotation(rotation)
    return document, page


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
@pytest.mark.parametrize(
    "coordinates",
    [
        (10.0, 20.0, 100.0, 60.0),
        (200.0, 300.0, 450.0, 500.0),
        (0.0, 0.0, 600.0, 800.0),
    ],
)
def test_native_coordinate_round_trip_for_twelve_rotation_samples(
    rotation: int,
    coordinates: tuple[float, float, float, float],
) -> None:
    document, page = page_with_rotation(rotation)
    try:
        transformer = CoordinateTransformer.from_page(page, render_scale=2)
        source = CanonicalBoundingBox(
            x0=coordinates[0],
            y0=coordinates[1],
            x1=coordinates[2],
            y1=coordinates[3],
        )

        canonical = transformer.native_to_canonical(source)
        restored = transformer.canonical_to_native(canonical)

        assert restored.x0 == pytest.approx(source.x0, abs=1e-5)
        assert restored.y0 == pytest.approx(source.y0, abs=1e-5)
        assert restored.x1 == pytest.approx(source.x1, abs=1e-5)
        assert restored.y1 == pytest.approx(source.y1, abs=1e-5)
        assert 0 <= canonical.x0 <= canonical.x1 <= transformer.page_width
        assert 0 <= canonical.y0 <= canonical.y1 <= transformer.page_height
    finally:
        document.close()


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_render_pixel_coordinate_round_trip_at_two_x(rotation: int) -> None:
    document, page = page_with_rotation(rotation)
    try:
        transformer = CoordinateTransformer.from_page(page, render_scale=2)
        canonical = CanonicalBoundingBox(x0=25, y0=30, x1=150, y1=180)

        pixels = transformer.canonical_to_render_pixels(canonical)
        restored = transformer.render_pixels_to_canonical(pixels)

        assert pixels.x0 == pytest.approx(canonical.x0 * 2)
        assert pixels.y1 == pytest.approx(canonical.y1 * 2)
        assert restored == canonical
    finally:
        document.close()


def test_normalized_coordinate_round_trip() -> None:
    document, page = page_with_rotation(90)
    try:
        transformer = CoordinateTransformer.from_page(page, render_scale=2)
        canonical = CanonicalBoundingBox(x0=80, y0=60, x1=400, y1=300)

        normalized = transformer.normalize(canonical)
        restored = transformer.denormalize(normalized)

        assert normalized.x0 == pytest.approx(0.1)
        assert normalized.y0 == pytest.approx(0.1)
        assert restored == canonical
    finally:
        document.close()


def test_cropbox_text_coordinates_remain_inside_visible_page() -> None:
    document = fitz.open()
    page = document.new_page(width=612, height=792)
    page.insert_text((60, 90), "CropBox evidence", fontsize=11)
    page.set_cropbox(fitz.Rect(24, 36, 594, 762))
    stream = BytesIO()
    document.save(stream, no_new_id=True)
    document.close()

    with fitz.open(stream=stream.getvalue(), filetype="pdf") as reopened:
        page = reopened[0]
        line_bbox = page.get_text("dict")["blocks"][0]["lines"][0]["bbox"]
        transformer = CoordinateTransformer.from_page(page, render_scale=2)
        canonical = transformer.native_to_canonical(line_bbox)

        assert transformer.page_width == 570
        assert transformer.page_height == 726
        assert 0 <= canonical.x0 < canonical.x1 <= 570
        assert 0 <= canonical.y0 < canonical.y1 <= 726


def test_coordinate_transformer_rejects_non_positive_render_scale() -> None:
    document, page = page_with_rotation(0)
    try:
        with pytest.raises(ValueError, match="render scale"):
            CoordinateTransformer.from_page(page, render_scale=0)
    finally:
        document.close()
