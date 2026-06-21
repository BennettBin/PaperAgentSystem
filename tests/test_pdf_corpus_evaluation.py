import json
from difflib import SequenceMatcher
from io import BytesIO
from pathlib import Path

import fitz
import pytest

from document_processing.pdf_parser import PyMuPDFParser

CORPUS = Path(__file__).parent / "fixtures" / "pdf_corpus" / "ground_truth.json"


def render(spec: dict) -> bytes:
    document = fitz.open()
    page = document.new_page(width=600, height=800)
    page.insert_text((40, 25), f"Corpus {spec['id']}", fontsize=8)
    page.insert_text((40, 70), spec["heading"], fontsize=16)
    if spec["layout"] == "single":
        for index, text in enumerate(spec["body"]):
            page.insert_text((40, 110 + index * 30), text, fontsize=11)
    else:
        for index, text in enumerate(spec["left"]):
            page.insert_text((40, 110 + index * 30), text, fontsize=11)
        for index, text in enumerate(spec["right"]):
            page.insert_text((330, 110 + index * 30), text, fontsize=11)
    page.insert_text((280, 780), "Page 1", fontsize=8)
    stream = BytesIO()
    document.save(stream)
    document.close()
    return stream.getvalue()


@pytest.mark.asyncio
async def test_ten_paper_structure_ground_truth_metrics() -> None:
    specs = json.loads(CORPUS.read_text("utf-8"))
    parser = PyMuPDFParser()
    extraction_scores = []
    ordering_scores = []
    section_tp = section_fp = section_fn = 0
    page_matches = 0
    for spec in specs:
        parsed = await parser.parse(render(spec), f"{spec['id']}.pdf")
        expected_blocks = (
            spec["body"]
            if spec["layout"] == "single"
            else [*spec["left"], *spec["right"]]
        )
        expected_text = " ".join([spec["heading"], *expected_blocks])
        extracted = " ".join(parsed.full_text.split())
        extraction_scores.append(SequenceMatcher(None, expected_text, extracted).ratio())
        observed = [
            block.text
            for block in parsed.pages[0].blocks
            if block.text in expected_blocks
        ]
        ordering_scores.append(observed == expected_blocks)
        predicted = {section.title for section in parsed.sections}
        truth = {spec["heading"]}
        section_tp += len(predicted & truth)
        section_fp += len(predicted - truth)
        section_fn += len(truth - predicted)
        page_matches += int(
            parsed.pages[0].page_number == 1
            and all(block.page_number == 1 for block in parsed.pages[0].blocks)
        )

    precision = section_tp / (section_tp + section_fp)
    recall = section_tp / (section_tp + section_fn)
    section_f1 = 2 * precision * recall / (precision + recall)
    assert len(specs) == 10
    assert sum(extraction_scores) / len(specs) >= 0.98
    assert sum(ordering_scores) / len(specs) >= 0.95
    assert section_f1 >= 0.90
    assert page_matches / len(specs) >= 0.98
