"""Render canonical L02 logical pages into reproducible PDF layout profiles."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import fitz  # type: ignore[import-untyped]

PAGE_WIDTH = 612
PAGE_HEIGHT = 792
MARGIN = 42


def _insert_page_text(page: fitz.Page, text: str, *, profile: str, language: str) -> None:
    font_name = "china-s" if language == "zh" else "helv"
    if profile == "double_column":
        midpoint = max(1, len(text) // 2)
        split_at = text.rfind(" ", 0, midpoint)
        if split_at < len(text) // 4:
            split_at = midpoint
        gap = 14
        column_width = (PAGE_WIDTH - 2 * MARGIN - gap) / 2
        left = fitz.Rect(MARGIN, MARGIN, MARGIN + column_width, PAGE_HEIGHT - MARGIN)
        right = fitz.Rect(
            MARGIN + column_width + gap,
            MARGIN,
            PAGE_WIDTH - MARGIN,
            PAGE_HEIGHT - MARGIN,
        )
        page.insert_textbox(left, text[:split_at], fontname=font_name, fontsize=7, lineheight=1.1)
        page.insert_textbox(right, text[split_at:], fontname=font_name, fontsize=7, lineheight=1.1)
        return
    page.insert_textbox(
        fitz.Rect(MARGIN, MARGIN, PAGE_WIDTH - MARGIN, PAGE_HEIGHT - MARGIN),
        text,
        fontname=font_name,
        fontsize=7,
        lineheight=1.1,
    )


def render_document(document: dict[str, Any], output_path: Path) -> None:
    profile = str(document["render_profile"])
    language = str(document["language"])
    output = fitz.open()
    for logical_page in document["pages"]:
        text = f"{logical_page['section']}\n\n{logical_page['text']}"
        if profile == "degraded_scan":
            clean = fitz.open()
            clean_page = clean.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
            _insert_page_text(clean_page, text, profile="single_column", language=language)
            pixmap = clean_page.get_pixmap(
                matrix=fitz.Matrix(0.85, 0.85), colorspace=fitz.csGRAY, alpha=False
            )
            page = output.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
            page.insert_image(page.rect, stream=pixmap.tobytes("png"))
            clean.close()
        else:
            page = output.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
            _insert_page_text(page, text, profile=profile, language=language)
    output.set_metadata(
        {
            "title": str(document["title"]),
            "subject": f"PaperAgent L02 reproducible {profile} evaluation rendering",
            "producer": "PaperAgent evaluation.datasets.render v1",
            "creationDate": "D:20260721000000Z",
            "modDate": "D:20260721000000Z",
        }
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output.save(output_path, garbage=4, deflate=True, no_new_id=True)
    output.close()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def render_release_samples(
    documents: list[dict[str, Any]], output_root: Path
) -> dict[str, Any]:
    samples: list[dict[str, Any]] = []
    for profile in ("single_column", "double_column", "degraded_scan"):
        eligible = [item for item in documents if item["render_profile"] == profile]
        if not eligible:
            raise ValueError(f"no document available for render profile {profile}")
        document = min(eligible, key=lambda item: (len(item["pages"]), item["paper_id"]))
        output_path = output_root / f"{profile}.pdf"
        render_document(document, output_path)
        samples.append(
            {
                "profile": profile,
                "paper_id": document["paper_id"],
                "path": f"render_samples/{output_path.name}",
                "page_count": len(document["pages"]),
                "sha256": _sha256_file(output_path),
            }
        )
    manifest = {
        "schema_version": "1.0",
        "render_contract": "logical page number equals rendered PDF page number",
        "samples": samples,
    }
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest
