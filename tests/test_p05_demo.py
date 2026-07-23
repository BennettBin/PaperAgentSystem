from pathlib import Path

from evaluation.p05_demo import build_demo, write_demo


def test_offline_demo_has_provenance_for_plan_roles_citations_verifier_and_metrics(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[1]
    demo = build_demo(root)

    assert [step.kind for step in demo.steps] == [
        "route",
        "plan_change",
        "agent_roles",
        "citations",
        "verifier",
        "metrics",
    ]
    assert all(step.source_artifact for step in demo.steps)
    assert demo.steps[0].data["production_default"] == "safe_rag"
    assert demo.steps[1].truth_class == "unit_fixture"
    assert demo.steps[2].truth_class == "offline_real_model"
    assert demo.steps[3].data["evidence_count"] > 0
    assert demo.steps[5].data["total_tokens"] > 0
    assert demo.steps[5].data["latency_ms"] > 0
    serialized = demo.model_dump_json()
    assert "hidden_reasoning" not in serialized
    assert "chain_of_thought" not in serialized

    paths = write_demo(demo, tmp_path)
    assert paths["json"].exists()
    assert "NO-GO" in paths["markdown"].read_text("utf-8")
