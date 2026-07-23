import json
from pathlib import Path

from evaluation.p04_final_report import build_p04_report, write_p04_report


def test_final_report_has_traceable_numbers_ci_negative_results_and_unavailable_ablations(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[1]
    report = build_p04_report(root)

    assert set(report.systems) == {
        "b0_vanilla_rag",
        "b1_fixed_workflow",
        "b2_bounded_react",
        "b3_full_4b",
        "production_safe_path",
    }
    assert report.systems["production_safe_path"].reused_from == "b1_fixed_workflow"
    for system in report.systems.values():
        assert system.sample_count == 300
        assert set(system.slices) == {"difficulty", "task_family", "language"}
        assert sum(item.sample_count for item in system.slices["difficulty"].values()) == 300
        for metric in system.metrics.values():
            assert metric.denominator >= 0
            if metric.value is not None:
                assert metric.confidence_interval is not None
                assert metric.source_artifact
        for dimension in system.slices.values():
            for item in dimension.values():
                assert item.metrics["task_success"].confidence_interval is not None
    assert set(report.ablations) == {"planner", "multi_agent", "sft", "cascade"}
    assert report.ablations["planner"].decision == "no_go"
    assert report.ablations["multi_agent"].decision == "no_go"
    assert report.ablations["sft"].decision == "unavailable"
    assert report.ablations["cascade"].decision == "unavailable"
    assert report.human_audit.sample_rate >= 0.10
    assert report.human_audit.scope == "dataset_answer_type_gold_not_final_output"
    assert len(report.failures) >= 3
    assert report.limitations

    paths = write_p04_report(report, tmp_path)
    payload = json.loads(paths["json"].read_text("utf-8"))
    assert payload["reproducibility"]["dataset_version"] == "paperagent-eval-v1"
    assert "NO-GO" in paths["markdown"].read_text("utf-8")


def test_public_metric_values_reproduce_frozen_l05_source() -> None:
    root = Path(__file__).resolve().parents[1]
    report = build_p04_report(root)
    source = json.loads(
        (root / "evaluation" / "reports" / "l05_baselines_v1" / "baseline_report.json").read_text(
            "utf-8"
        )
    )
    for expected in source["systems"]:
        actual = report.systems[expected["system_id"]]
        assert actual.metrics["task_success"].value == expected["overall"]["task_success"]
        assert actual.metrics["citation_recall"].value == expected["overall"]["citation_recall"]
        assert actual.metrics["p95_latency_ms"].value == expected["latency_p95_ms"]
