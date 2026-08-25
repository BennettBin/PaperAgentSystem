from __future__ import annotations

import json
from pathlib import Path

from backend.document_processing.config import DocumentProcessingConfig
from backend.document_processing.preflight import PDFPreflight
from backend.document_processing.profiler import PageProfiler
from backend.document_processing.router import DeterministicParseRouter
from backend.document_processing.schema_v2 import ParseRoute

ROOT = Path(__file__).resolve().parents[1]
CORPUS_ROOT = ROOT / "tests" / "fixtures" / "document_parsing_v2"


def test_router_matches_all_twenty_bounded_corpus_expectations() -> None:
    manifest = json.loads((CORPUS_ROOT / "manifest.json").read_text(encoding="utf-8"))
    profiler = PageProfiler()
    router = DeterministicParseRouter()

    assert 10 <= len(manifest["samples"]) <= 30
    for sample in manifest["samples"]:
        data = (CORPUS_ROOT / sample["path"]).read_bytes()
        preflight = PDFPreflight().inspect(data, sample["path"])
        signals = profiler.profile_document(data)
        plan = router.route_document(signals)

        assert preflight.page_count == len(signals) == sample["page_count"]
        assert plan.document_route.value == sample["expected_route"], sample["case_id"]
        assert all(
            decision.reasons
            for decision in plan.decisions
            if decision.route is not ParseRoute.FAST_NATIVE
        )


def test_clean_native_samples_never_select_layout_or_vlm() -> None:
    router = DeterministicParseRouter()
    profiler = PageProfiler()
    manifest = json.loads((CORPUS_ROOT / "manifest.json").read_text(encoding="utf-8"))

    samples = [item for item in manifest["samples"] if item["category"] == "native_single"]
    assert samples
    for sample in samples:
        signals = profiler.profile_document((CORPUS_ROOT / sample["path"]).read_bytes())
        plan = router.route_document(signals)
        assert plan.document_route is ParseRoute.FAST_NATIVE
        assert plan.vlm_page_count == 0
        assert all(decision.route is ParseRoute.FAST_NATIVE for decision in plan.decisions)


def test_scans_select_vlm_and_complex_native_pages_select_layout_first() -> None:
    router = DeterministicParseRouter()
    profiler = PageProfiler()

    scan = profiler.profile_document((CORPUS_ROOT / "scan-01.pdf").read_bytes())
    double = profiler.profile_document((CORPUS_ROOT / "native-double-01.pdf").read_bytes())
    table = profiler.profile_document((CORPUS_ROOT / "table-01.pdf").read_bytes())

    scan_decision = router.route_document(scan).decisions[0]
    double_decision = router.route_document(double).decisions[0]
    table_decision = router.route_document(table).decisions[0]

    assert scan_decision.route is ParseRoute.DOCUMENT_VLM
    assert "no_native_text_image_page" in scan_decision.reasons
    assert double_decision.route is ParseRoute.LAYOUT_NATIVE
    assert "multi_column_layout" in double_decision.reasons
    assert table_decision.route is ParseRoute.LAYOUT_NATIVE
    assert "table_structure_detected" in table_decision.reasons


def test_mixed_document_routes_pages_independently() -> None:
    signals = PageProfiler().profile_document((CORPUS_ROOT / "mixed-01.pdf").read_bytes())
    plan = DeterministicParseRouter().route_document(signals)

    assert [decision.route for decision in plan.decisions] == [
        ParseRoute.FAST_NATIVE,
        ParseRoute.DOCUMENT_VLM,
    ]
    assert plan.document_route is ParseRoute.DOCUMENT_VLM


def test_vlm_page_budget_is_explicit_and_does_not_silently_change_routes() -> None:
    signals = PageProfiler().profile_document((CORPUS_ROOT / "mixed-01.pdf").read_bytes())
    scan_signal = PageProfiler().profile_document((CORPUS_ROOT / "scan-01.pdf").read_bytes())[0]
    pages = (signals[1].model_copy(update={"page_number": 1}), scan_signal.model_copy(update={"page_number": 2}))
    plan = DeterministicParseRouter(
        DocumentProcessingConfig(vlm_max_pages_per_document=1)
    ).route_document(pages)

    assert plan.budget_exceeded is True
    assert plan.vlm_page_count == 2
    assert plan.blocked_page_numbers == (2,)
    assert all(decision.route is ParseRoute.DOCUMENT_VLM for decision in plan.decisions)


def test_page_profile_preserves_router_decision_and_signals() -> None:
    signals = PageProfiler().profile_document((CORPUS_ROOT / "formula-01.pdf").read_bytes())[0]
    profile = DeterministicParseRouter().profile(signals)

    assert profile.page_number == signals.page_number
    assert profile.proposed_route is ParseRoute.LAYOUT_NATIVE
    assert profile.has_formulas is True
    assert "formula_structure_detected" in profile.route_reasons
