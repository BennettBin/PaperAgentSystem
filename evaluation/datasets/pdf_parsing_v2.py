"""Build the bounded, reproducible PDF-V00 hybrid parsing corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

import fitz  # type: ignore[import-untyped]

PAGE_WIDTH = 612
PAGE_HEIGHT = 792
BUILD_VERSION = "pdf-v00-1"
ParseRoute = Literal["fast_native", "layout_native", "document_vlm"]


@dataclass(frozen=True, slots=True)
class CorpusCase:
    case_id: str
    category: str
    expected_route: ParseRoute
    key_spans: tuple[str, ...]
    expected_element_types: tuple[str, ...]
    renderer: Callable[[Path, "CorpusCase"], None]
    page_count: int = 1

    @property
    def filename(self) -> str:
        return f"{self.case_id}.pdf"


def _metadata(case: CorpusCase) -> dict[str, str]:
    return {
        "title": case.case_id,
        "subject": f"PaperAgent {BUILD_VERSION} {case.category}",
        "producer": f"PaperAgent {BUILD_VERSION}",
        "creationDate": "D:20260805000000Z",
        "modDate": "D:20260805000000Z",
    }


def _save(document: fitz.Document, output_path: Path, case: CorpusCase) -> None:
    document.set_metadata(_metadata(case))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    document.save(output_path, garbage=4, deflate=True, no_new_id=True)
    document.close()


def _new_page(document: fitz.Document) -> fitz.Page:
    return document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)


def _render_single(output_path: Path, case: CorpusCase) -> None:
    document = fitz.open()
    page = _new_page(document)
    page.insert_text((42, 42), "PaperAgent Parsing Corpus", fontsize=8)
    page.insert_text((42, 86), "1 Introduction", fontsize=16)
    page.insert_textbox(
        fitz.Rect(42, 115, 570, 690),
        case.key_spans[0]
        + " This born-digital page has selectable text, stable coordinates, and a simple reading order.",
        fontsize=11,
        lineheight=1.25,
    )
    page.insert_text((280, 760), "Page 1", fontsize=8)
    _save(document, output_path, case)


def _render_double(output_path: Path, case: CorpusCase) -> None:
    document = fitz.open()
    page = _new_page(document)
    page.insert_text((42, 48), "2 Methods", fontsize=16)
    page.insert_textbox(
        fitz.Rect(42, 90, 292, 700),
        case.key_spans[0]
        + " Left-column evidence continues in document order. " * 8,
        fontsize=9,
        lineheight=1.2,
    )
    page.insert_textbox(
        fitz.Rect(320, 90, 570, 700),
        case.key_spans[1]
        + " Right-column evidence follows the complete left column. " * 8,
        fontsize=9,
        lineheight=1.2,
    )
    _save(document, output_path, case)


def _scanned_page(text: str) -> bytes:
    source = fitz.open()
    page = _new_page(source)
    page.insert_text((42, 80), "3 Scanned Evidence", fontsize=16)
    page.insert_textbox(
        fitz.Rect(42, 115, 570, 690),
        text + " This page intentionally contains no selectable PDF text layer.",
        fontsize=12,
        lineheight=1.3,
    )
    pixmap = page.get_pixmap(
        matrix=fitz.Matrix(1.1, 1.1),
        colorspace=fitz.csGRAY,
        alpha=False,
    )
    image = pixmap.tobytes("png")
    source.close()
    return image


def _render_scan(output_path: Path, case: CorpusCase) -> None:
    document = fitz.open()
    page = _new_page(document)
    page.insert_image(page.rect, stream=_scanned_page(case.key_spans[0]))
    _save(document, output_path, case)


def _render_table(output_path: Path, case: CorpusCase) -> None:
    document = fitz.open()
    page = _new_page(document)
    page.insert_text((42, 62), "4 Results", fontsize=16)
    left, top, right, bottom = 70, 150, 542, 390
    for x in (left, 230, 390, right):
        page.draw_line((x, top), (x, bottom), color=(0, 0, 0), width=1)
    for y in (top, 210, 270, 330, bottom):
        page.draw_line((left, y), (right, y), color=(0, 0, 0), width=1)
    values = (
        ("Model", "Accuracy", "F1"),
        ("Baseline", "81.2", "79.8"),
        ("PaperAgent", case.key_spans[0], case.key_spans[1]),
        ("Ablation", "84.0", "82.7"),
    )
    for row, row_values in enumerate(values):
        for column, value in enumerate(row_values):
            page.insert_text((80 + 160 * column, 185 + 60 * row), value, fontsize=10)
    page.insert_text((70, 420), f"Table 1: {case.case_id} benchmark results", fontsize=10)
    _save(document, output_path, case)


def _render_formula(output_path: Path, case: CorpusCase) -> None:
    document = fitz.open()
    page = _new_page(document)
    page.insert_text((42, 62), "5 Objective", fontsize=16)
    page.insert_textbox(
        fitz.Rect(42, 100, 570, 180),
        "The optimization objective is defined below and must remain an atomic evidence element.",
        fontsize=11,
    )
    page.draw_rect(fitz.Rect(90, 220, 520, 315), color=(0, 0, 0), width=0.8)
    page.insert_text((120, 268), case.key_spans[0], fontsize=15)
    page.insert_text((480, 300), case.key_spans[1], fontsize=11)
    _save(document, output_path, case)


def _render_mixed(output_path: Path, case: CorpusCase) -> None:
    document = fitz.open()
    native_page = _new_page(document)
    native_page.insert_text((42, 62), "6 Native Appendix", fontsize=16)
    native_page.insert_textbox(
        fitz.Rect(42, 100, 570, 690),
        case.key_spans[0] + " This first page has a reliable native text layer.",
        fontsize=11,
    )
    scan_page = _new_page(document)
    scan_page.insert_image(scan_page.rect, stream=_scanned_page(case.key_spans[1]))
    _save(document, output_path, case)


def _render_rotated(output_path: Path, case: CorpusCase) -> None:
    document = fitz.open()
    page = _new_page(document)
    page.insert_text((60, 90), "7 Rotated Evidence", fontsize=16)
    page.insert_textbox(
        fitz.Rect(60, 130, 550, 650),
        case.key_spans[0] + " Coordinates must map back to the visible rotated page.",
        fontsize=11,
    )
    if case.case_id.endswith("crop"):
        page.set_cropbox(fitz.Rect(24, 36, PAGE_WIDTH - 18, PAGE_HEIGHT - 30))
    else:
        page.set_rotation(90)
    _save(document, output_path, case)


def _render_image_dense(output_path: Path, case: CorpusCase) -> None:
    image_document = fitz.open()
    image_page = image_document.new_page(width=500, height=500)
    image_page.draw_rect(fitz.Rect(20, 20, 480, 480), color=(0.1, 0.2, 0.8), fill=(0.9, 0.9, 1))
    image_page.draw_circle((250, 250), 150, color=(0.8, 0.1, 0.1), fill=(1, 0.9, 0.9))
    image_page.insert_text((90, 255), case.key_spans[0], fontsize=18)
    image = image_page.get_pixmap(alpha=False).tobytes("png")
    image_document.close()

    document = fitz.open()
    page = _new_page(document)
    page.insert_image(fitz.Rect(42, 55, 570, 690), stream=image)
    page.insert_text((42, 730), f"Figure 1: {case.key_spans[1]}", fontsize=10)
    _save(document, output_path, case)


CASES = (
    *(
        CorpusCase(
            case_id=f"native-single-{index:02d}",
            category="native_single",
            expected_route="fast_native",
            key_spans=(f"NATIVE_SINGLE_TOKEN_{index}",),
            expected_element_types=("section_heading", "paragraph"),
            renderer=_render_single,
        )
        for index in range(1, 4)
    ),
    *(
        CorpusCase(
            case_id=f"native-double-{index:02d}",
            category="native_double",
            expected_route="layout_native",
            key_spans=(f"LEFT_COLUMN_TOKEN_{index}", f"RIGHT_COLUMN_TOKEN_{index}"),
            expected_element_types=("section_heading", "paragraph"),
            renderer=_render_double,
        )
        for index in range(1, 4)
    ),
    *(
        CorpusCase(
            case_id=f"scan-{index:02d}",
            category="scanned",
            expected_route="document_vlm",
            key_spans=(f"SCANNED_TOKEN_{index}",),
            expected_element_types=("section_heading", "paragraph"),
            renderer=_render_scan,
        )
        for index in range(1, 4)
    ),
    *(
        CorpusCase(
            case_id=f"table-{index:02d}",
            category="table_dense",
            expected_route="layout_native",
            key_spans=(f"{85 + index}.3", f"{83 + index}.1"),
            expected_element_types=("section_heading", "table", "table_cell", "caption"),
            renderer=_render_table,
        )
        for index in range(1, 4)
    ),
    *(
        CorpusCase(
            case_id=f"formula-{index:02d}",
            category="formula_dense",
            expected_route="layout_native",
            key_spans=(f"L_{index} = sum_i w_i * x_i", f"({index})"),
            expected_element_types=("section_heading", "paragraph", "equation"),
            renderer=_render_formula,
        )
        for index in range(1, 3)
    ),
    *(
        CorpusCase(
            case_id=f"mixed-{index:02d}",
            category="mixed_native_scan",
            expected_route="document_vlm",
            key_spans=(f"MIXED_NATIVE_TOKEN_{index}", f"MIXED_SCAN_TOKEN_{index}"),
            expected_element_types=("section_heading", "paragraph"),
            renderer=_render_mixed,
            page_count=2,
        )
        for index in range(1, 3)
    ),
    CorpusCase(
        case_id="rotated-01",
        category="rotated",
        expected_route="layout_native",
        key_spans=("ROTATED_PAGE_TOKEN",),
        expected_element_types=("section_heading", "paragraph"),
        renderer=_render_rotated,
    ),
    CorpusCase(
        case_id="rotated-crop",
        category="cropbox",
        expected_route="layout_native",
        key_spans=("CROPBOX_PAGE_TOKEN",),
        expected_element_types=("section_heading", "paragraph"),
        renderer=_render_rotated,
    ),
    *(
        CorpusCase(
            case_id=f"image-dense-{index:02d}",
            category="image_dense",
            expected_route="document_vlm",
            key_spans=(f"IMAGE_REGION_TOKEN_{index}", f"image dense sample {index}"),
            expected_element_types=("figure", "caption"),
            renderer=_render_image_dense,
        )
        for index in range(1, 3)
    ),
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _case_spec_sha256(case: CorpusCase) -> str:
    payload = {
        "case_id": case.case_id,
        "category": case.category,
        "expected_route": case.expected_route,
        "page_count": case.page_count,
        "key_spans": case.key_spans,
        "expected_element_types": case.expected_element_types,
        "build_version": BUILD_VERSION,
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_corpus(output_root: Path) -> dict[str, object]:
    output_root.mkdir(parents=True, exist_ok=True)
    samples: list[dict[str, object]] = []
    for case in CASES:
        output_path = output_root / case.filename
        case.renderer(output_path, case)
        samples.append(
            {
                "case_id": case.case_id,
                "category": case.category,
                "path": case.filename,
                "page_count": case.page_count,
                "expected_route": case.expected_route,
                "key_spans": [
                    {"text": text, "page_number": min(index + 1, case.page_count)}
                    for index, text in enumerate(case.key_spans)
                ],
                "expected_element_types": list(case.expected_element_types),
                "spec_sha256": _case_spec_sha256(case),
                "file_sha256": _sha256(output_path),
            }
        )
    manifest: dict[str, object] = {
        "schema_version": "2.0",
        "build_version": BUILD_VERSION,
        "sample_policy": "bounded deterministic project-generated corpus; 10-30 samples",
        "sample_count": len(samples),
        "coordinate_contract": "one-based page numbers; canonical PDF point coordinates",
        "samples": samples,
    }
    (output_root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_root", type=Path)
    arguments = parser.parse_args()
    manifest = build_corpus(arguments.output_root)
    print(json.dumps({"sample_count": manifest["sample_count"]}, sort_keys=True))


if __name__ == "__main__":
    main()

