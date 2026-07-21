from io import BytesIO

import fitz
import pytest

from document_processing.pdf_parser import PyMuPDFParser


def structured_pdf() -> bytes:
    document = fitz.open()
    page = document.new_page(width=600, height=800)
    page.insert_text((50, 55), "Contents", fontsize=18)
    page.insert_text((50, 90), "1 Introduction ........................ 2", fontsize=11)
    page.insert_text((50, 115), "2 Methods ............................. 3", fontsize=11)
    page.insert_text((50, 140), "2.1 Dataset ........................... 3", fontsize=11)

    page = document.new_page(width=600, height=800)
    page.insert_text((50, 60), "1 Introduction", fontsize=17)
    page.insert_text((50, 100), "Introduction body.", fontsize=11)
    page.insert_text((50, 150), "2 Methods", fontsize=17)
    page.insert_text((50, 190), "Methods overview.", fontsize=11)
    page.insert_text((50, 240), "2.1 Dataset", fontsize=14)
    page.insert_text((50, 280), "Dataset details.", fontsize=11)
    page.insert_text((50, 330), "2.2 Model Architecture", fontsize=14)
    page.insert_text((50, 370), "Architecture details.", fontsize=11)

    page = document.new_page(width=600, height=800)
    page.insert_text((50, 60), "3 Results", fontsize=17)
    page.insert_text((50, 100), "Results body.", fontsize=11)
    page.insert_text((50, 150), "References", fontsize=17)
    page.insert_text((50, 190), "1 Smith et al. 2024. A cited paper.", fontsize=11)
    page.insert_text((50, 240), "Appendix A Supplementary Results", fontsize=17)
    page.insert_text((50, 280), "Supplementary details.", fontsize=11)

    stream = BytesIO()
    document.save(stream)
    document.close()
    return stream.getvalue()


@pytest.mark.asyncio
async def test_parser_builds_numbered_section_tree_and_ignores_toc_entries() -> None:
    parsed = await PyMuPDFParser().parse(structured_pdf(), "structured.pdf")

    sections = {section.number or section.normalized_title: section for section in parsed.sections}
    assert {"1", "2", "2.1", "2.2", "3"} <= set(sections)
    assert sum(section.number == "1" for section in parsed.sections) == 1
    assert sections["2.1"].parent_section_id == sections["2"].section_id
    assert sections["2.2"].parent_section_id == sections["2"].section_id
    assert sections["2.1"].section_path == ["2 Methods", "2.1 Dataset"]
    assert sections["2.1"].heading_block_id not in sections["2.1"].block_ids
    assert all("Smith et al." not in section.title for section in parsed.sections)


@pytest.mark.asyncio
async def test_section_ranges_and_appendix_metadata_are_traceable() -> None:
    parsed = await PyMuPDFParser().parse(structured_pdf(), "structured.pdf")

    dataset = next(section for section in parsed.sections if section.number == "2.1")
    appendix = next(
        section for section in parsed.sections if section.normalized_title == "supplementary results"
    )
    blocks = {
        block.block_id: block
        for page in parsed.pages
        for block in page.blocks
    }
    assert dataset.page_start == dataset.page_end == 2
    assert [blocks[block_id].text for block_id in dataset.block_ids] == [
        "Dataset details."
    ]
    assert appendix.number == "A"
    assert appendix.heading_block_id
    assert appendix.ordinal > dataset.ordinal
