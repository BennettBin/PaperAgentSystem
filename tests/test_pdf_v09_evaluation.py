from __future__ import annotations

import json
from pathlib import Path

import pytest

from evaluation.pdf_hybrid_v2_evaluation import (
    ControlledEvaluationPipelineFactory,
    EvaluationEnvironment,
    evaluate_go_no_go,
    evaluate_pdf_v2_corpus,
    render_report_json,
    run_security_evaluation,
)

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "tests" / "fixtures" / "document_parsing_v2"
V1_REPORT = ROOT / "evaluation" / "reports" / "pdf_parsing_v1_baseline.json"


@pytest.fixture(scope="module")
def v2_report() -> dict[str, object]:
    return __import__("asyncio").run(
        evaluate_pdf_v2_corpus(
            CORPUS,
            V1_REPORT,
            pipeline_factory=ControlledEvaluationPipelineFactory(),
        )
    )


def test_fixed_twenty_sample_report_covers_every_required_dimension(
    v2_report: dict[str, object],
) -> None:
    metrics = v2_report["metrics"]
    assert v2_report["sample_count"] == 20
    assert set(metrics) >= {
        "text",
        "reading_order",
        "structure",
        "coordinates",
        "tables",
        "formulae",
        "retrieval",
        "performance",
        "cost",
        "quality",
    }
    assert metrics["text"]["key_span_recall"] == 1.0
    assert metrics["coordinates"]["valid_bbox_rate"] == 1.0
    assert metrics["coordinates"]["citation_jump_hit_rate"] == 1.0
    assert metrics["tables"]["cell_text_recall"] == 1.0
    assert metrics["formulae"]["latex_or_text_recall"] == 1.0
    assert metrics["retrieval"]["evidence_recall_at_5"] == 1.0
    assert 0 <= metrics["structure"]["heading_f1"] <= 1
    assert 0 <= metrics["structure"]["section_tree_f1"] <= 1


def test_route_performance_and_cost_are_reported_without_fast_path_averaging(
    v2_report: dict[str, object],
) -> None:
    performance = v2_report["metrics"]["performance"]
    cost = v2_report["metrics"]["cost"]

    assert set(performance["route_latency_ms"]) == {
        "fast_native",
        "layout_native",
        "document_vlm",
    }
    assert all(
        set(values) == {"p50", "p95", "per_page_p50", "per_page_p95"}
        for values in performance["route_latency_ms"].values()
    )
    assert cost["fast_native_vlm_call_rate"] == 0.0
    assert cost["vlm_page_count"] == 7
    assert cost["gpu_page_count"] == 7
    assert cost["rendered_pixel_count"] > 0
    assert cost["service_call_count"] == 7
    assert cost["fallback_count"] == 0
    assert cost["retry_count"] == 0


def test_complex_evidence_improves_over_v1_and_clean_pdf_does_not_regress(
    v2_report: dict[str, object],
) -> None:
    comparison = v2_report["comparison_to_v1"]

    assert comparison["clean_native_span_recall_delta"] >= 0
    assert comparison["complex_evidence_recall_delta"] > 0
    assert comparison["valid_bbox_rate_delta"] >= 0


@pytest.mark.asyncio
async def test_security_evaluation_covers_bounded_failure_and_injection_paths() -> None:
    result = await run_security_evaluation(CORPUS)

    assert result == {
        "malformed_pdf_rejected": True,
        "oversized_page_rejected": True,
        "prompt_injection_is_data_only": True,
        "vlm_timeout_not_ready": True,
        "vlm_oom_not_ready": True,
        "vlm_disabled_not_ready": True,
        "docling_failure_degrades": True,
        "failed_document_not_index_ready": True,
    }


def test_go_no_go_separates_controlled_functional_gate_from_real_deployment(
    v2_report: dict[str, object],
) -> None:
    security = __import__("asyncio").run(run_security_evaluation(CORPUS))
    decision = evaluate_go_no_go(
        v2_report,
        security,
        EvaluationEnvironment(
            docling_available=False,
            document_vlm_available=False,
            gpu_profile_recorded=False,
        ),
    )

    assert decision["functional_gate"] == "go"
    assert decision["deployment_gate"] == "no_go"
    assert decision["recommendation"] == "no_go"
    assert "real_docling_unavailable" in decision["blocking_reasons"]
    assert "real_document_vlm_unavailable" in decision["blocking_reasons"]
    assert "gpu_profile_missing" in decision["blocking_reasons"]


def test_report_json_is_deterministic_and_contains_no_extracted_document_body(
    v2_report: dict[str, object],
) -> None:
    first = render_report_json(v2_report)
    second = render_report_json(v2_report)
    payload = json.loads(first)

    assert first == second
    assert "SCANNED_TOKEN" not in first
    assert "MIXED_NATIVE_TOKEN" not in first
    assert payload["truth_class"] == "controlled_parser_contract_evaluation"
    assert all("full_text" not in case for case in payload["cases"])
