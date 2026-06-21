from io import BytesIO

import fitz
import pytest

from document_processing.pdf_parser import PyMuPDFParser


def make_pdf(*, two_columns: bool = False, pages: int = 2) -> bytes:
    document = fitz.open()
    for page_index in range(pages):
        page = document.new_page(width=600, height=800)
        page.insert_text((40, 25), "Repeated Journal Header", fontsize=8)
        page.insert_text((280, 780), f"Page {page_index + 1}", fontsize=8)
        page.insert_text((40, 70), "1 Introduction", fontsize=16)
        if two_columns:
            for row in range(5):
                page.insert_text(
                    (40, 110 + row * 24),
                    f"LEFT-{page_index}-{row} alpha beta gamma",
                    fontsize=11,
                )
                page.insert_text(
                    (330, 110 + row * 24),
                    f"RIGHT-{page_index}-{row} delta epsilon",
                    fontsize=11,
                )
        else:
            page.insert_text(
                (40, 110),
                "This paper presents a reproducible parsing evaluation.",
                fontsize=11,
            )
            page.insert_text((40, 150), "2 Methods", fontsize=16)
            page.insert_text(
                (40, 185),
                "The method preserves page coordinates and reading order.",
                fontsize=11,
            )
    stream = BytesIO()
    document.save(stream)
    document.close()
    return stream.getvalue()


@pytest.mark.asyncio
async def test_parser_extracts_pages_bbox_headers_footers_and_sections() -> None:
    parsed = await PyMuPDFParser().parse(make_pdf(), "paper.pdf")

    assert parsed.page_count == 2
    assert parsed.pages[0].page_number == 1
    assert all(block.bbox.x0 >= 0 for page in parsed.pages for block in page.blocks)
    assert "Repeated Journal Header" in parsed.headers
    assert any("Page 1" in footer for footer in parsed.footers)
    assert [section.title for section in parsed.sections][:2] == [
        "1 Introduction",
        "2 Methods",
    ]
    assert parsed.quality.score >= 0.9


@pytest.mark.asyncio
async def test_double_column_reading_order_is_column_major() -> None:
    parsed = await PyMuPDFParser().parse(
        make_pdf(two_columns=True, pages=1),
        "columns.pdf",
    )
    body = [block.text for block in parsed.pages[0].blocks if "LEFT-" in block.text or "RIGHT-" in block.text]

    assert body[:5] == [f"LEFT-0-{row} alpha beta gamma" for row in range(5)]
    assert body[5:] == [f"RIGHT-0-{row} delta epsilon" for row in range(5)]


@pytest.mark.asyncio
async def test_parser_quality_evaluation_thresholds() -> None:
    parser = PyMuPDFParser()
    character_scores = []
    page_mapping = []
    section_tp = section_fp = section_fn = 0
    ordering = []
    for index in range(50):
        expected = "This paper presents a reproducible parsing evaluation."
        parsed = await parser.parse(make_pdf(pages=1), f"normal-{index}.pdf")
        character_scores.append(len(set(expected) & set(parsed.full_text)) / len(set(expected)))
        page_mapping.append(parsed.pages[0].page_number == 1)
        predicted = {section.title for section in parsed.sections}
        truth = {"1 Introduction", "2 Methods"}
        section_tp += len(predicted & truth)
        section_fp += len(predicted - truth)
        section_fn += len(truth - predicted)

        columns = await parser.parse(
            make_pdf(two_columns=True, pages=1),
            f"columns-{index}.pdf",
        )
        body = [block.text for block in columns.pages[0].blocks if "LEFT-" in block.text or "RIGHT-" in block.text]
        ordering.append(body == [
            *(f"LEFT-0-{row} alpha beta gamma" for row in range(5)),
            *(f"RIGHT-0-{row} delta epsilon" for row in range(5)),
        ])

    precision = section_tp / (section_tp + section_fp)
    recall = section_tp / (section_tp + section_fn)
    section_f1 = 2 * precision * recall / (precision + recall)
    assert sum(character_scores) / len(character_scores) >= 0.98
    assert sum(ordering) / len(ordering) >= 0.95
    assert section_f1 >= 0.90
    assert sum(page_mapping) / len(page_mapping) >= 0.98
