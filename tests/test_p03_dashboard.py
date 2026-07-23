import json
import time
from pathlib import Path

import pytest
from pydantic import ValidationError

from evaluation.dashboard import (
    DashboardAction,
    DashboardCase,
    DashboardCitation,
    DashboardFilters,
    DashboardObservation,
    DashboardStep,
    OfflineEvaluationDashboard,
    PublicTraceEvent,
)


def _case(index: int, system_id: str = "candidate") -> DashboardCase:
    success = index % 4 == 0
    return DashboardCase(
        report_version="report-v1",
        case_id=f"case-{index:03d}",
        system_id=system_id,
        task_family="comparison" if index % 2 else "qa",
        difficulty="L4" if index % 3 else "L3",
        language="zh" if index % 5 else "en",
        model="qwen3.5:4b",
        error_category=None if success else "verification",
        task_success=success,
        claim_support=0.9 if success else 0.4,
        input_tokens=100 + index,
        output_tokens=20,
        model_calls=2,
        four_b_calls=1,
        latency_ms=1000 + index,
        monetary_cost=0.0,
        plan=[DashboardStep(title="retrieve evidence", status="completed")],
        actions=[DashboardAction(name="hybrid_search", status="completed")],
        observations=[DashboardObservation(code="evidence_found", status="ok")],
        citations=[DashboardCitation(evidence_id="E1", source_id="paper-1", page=2)],
        public_trace=[PublicTraceEvent(kind="step", title="evidence retrieved", status="ok")],
    )


def test_dashboard_filters_metrics_ci_and_metric_drilldown_match_rows() -> None:
    dashboard = OfflineEvaluationDashboard([_case(index) for index in range(20)])
    response = dashboard.query(
        DashboardFilters(task_family="comparison", language="zh")
    )

    expected = [
        _case(index)
        for index in range(20)
        if index % 2 == 1 and index % 5 != 0
    ]
    assert response.row_count == len(expected)
    assert response.metrics["task_success"].denominator == len(expected)
    assert response.metrics["task_success"].confidence_interval is not None
    assert response.metrics["claim_support"].denominator == len(expected)
    assert response.metrics["total_tokens"].value == pytest.approx(
        sum(item.total_tokens for item in expected) / len(expected)
    )
    assert response.metrics["four_b_call_rate"].value == 0.5
    assert response.metrics["p95_latency_ms"].case_ids == [
        item.case_id for item in expected
    ]
    assert response.metrics["cost_per_success"].denominator == sum(
        item.task_success for item in expected
    )


def test_every_metric_drills_down_and_case_detail_is_public_only() -> None:
    dashboard = OfflineEvaluationDashboard([_case(index) for index in range(10)])
    response = dashboard.query(DashboardFilters(error_category="verification"))

    assert all(metric.case_ids for metric in response.metrics.values())
    detail = dashboard.case_detail("case-001", "candidate")
    serialized = detail.model_dump_json()
    assert "hybrid_search" in serialized
    assert "paper-1" in serialized
    assert "hidden_reasoning" not in serialized
    assert "chain_of_thought" not in serialized
    assert "paper full text" not in serialized


def test_baseline_candidate_comparison_is_paired_and_versioned() -> None:
    baseline = [_case(index, "baseline") for index in range(12)]
    candidate = [
        _case(index, "candidate").model_copy(update={"task_success": index % 3 == 0})
        for index in range(12)
    ]
    comparison = OfflineEvaluationDashboard(baseline + candidate).compare(
        "baseline", "candidate"
    )

    assert comparison.paired_case_count == 12
    assert comparison.task_success_delta.confidence == 0.95
    assert comparison.claim_support_delta is not None


def test_dashboard_schema_rejects_private_or_hidden_fields() -> None:
    payload = _case(1).model_dump(mode="python")
    payload["hidden_reasoning"] = "secret chain"
    with pytest.raises(ValidationError):
        DashboardCase.model_validate(payload)
    payload = _case(1).model_dump(mode="python")
    payload["citations"][0]["quote"] = "private paper full text"
    with pytest.raises(ValidationError):
        DashboardCase.model_validate(payload)


def test_real_300_row_jsonl_load_filter_and_drilldown_p95_under_two_seconds(
    tmp_path: Path,
) -> None:
    path = tmp_path / "dashboard_cases.jsonl"
    path.write_text(
        "\n".join(_case(index).model_dump_json() for index in range(300)) + "\n",
        encoding="utf-8",
    )
    started = time.perf_counter()
    durations = []
    for _ in range(20):
        lap = time.perf_counter()
        dashboard = OfflineEvaluationDashboard.from_jsonl(path)
        response = dashboard.query(DashboardFilters(difficulty="L4"))
        dashboard.case_detail(response.case_ids[0], "candidate")
        durations.append(time.perf_counter() - lap)
    elapsed = time.perf_counter() - started

    durations.sort()
    p95 = durations[int(0.95 * (len(durations) - 1))]
    assert p95 < 2.0
    assert elapsed < 40.0
    assert json.loads(path.read_text("utf-8").splitlines()[0])["report_version"] == "report-v1"


def test_frozen_l05_dashboard_metrics_match_source_report() -> None:
    root = Path(__file__).resolve().parents[1]
    dashboard = OfflineEvaluationDashboard.from_jsonl(
        root / "evaluation" / "reports" / "p03_dashboard_v1" / "cases.jsonl"
    )
    source = json.loads(
        (root / "evaluation" / "reports" / "l05_baselines_v1" / "baseline_report.json").read_text(
            "utf-8"
        )
    )
    expected = next(item for item in source["systems"] if item["system_id"] == "b3_full_4b")
    response = dashboard.query(DashboardFilters(system_id="b3_full_4b"))

    assert response.row_count == 300
    assert response.metrics["task_success"].value == expected["overall"]["task_success"]
    assert response.metrics["total_tokens"].value == pytest.approx(
        (expected["input_tokens"] + expected["output_tokens"]) / 300
    )
    assert response.metrics["four_b_call_rate"].value == expected["four_b_call_rate"]
    assert response.metrics["p95_latency_ms"].value == expected["latency_p95_ms"]
    assert response.metrics["claim_support"].value is None
    assert response.metrics["claim_support"].denominator == 0


def test_frozen_n05_claim_support_and_paired_delta_match_source_report() -> None:
    root = Path(__file__).resolve().parents[1]
    dashboard = OfflineEvaluationDashboard.from_jsonl(
        root / "evaluation" / "reports" / "p03_dashboard_v1" / "cases.jsonl"
    )
    source = json.loads(
        (root / "evaluation" / "reports" / "n05_multi_agent_ablation_v1" / "report.json").read_text(
            "utf-8"
        )
    )
    full = dashboard.query(DashboardFilters(system_id="full_system"))
    comparison = dashboard.compare("single_agent", "full_system")

    assert full.row_count == 90
    assert full.metrics["claim_support"].value == pytest.approx(
        source["per_system"]["full_system"]["claim_support_rate"]
    )
    assert comparison.claim_support_delta is not None
    assert comparison.claim_support_delta.estimate == pytest.approx(
        source["metrics"]["claim_support_delta"]
    )
