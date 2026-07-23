"""Provenance-first offline interview demo over frozen project evidence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DemoStep(_StrictModel):
    sequence: int = Field(ge=1)
    kind: str
    title: str
    truth_class: str
    source_artifact: str
    data: dict[str, Any]


class OfflineDemo(_StrictModel):
    schema_version: str = "1.0"
    demo_version: str = "p05-offline-demo-v1"
    scenario: str
    policy_notice: str
    steps: list[DemoStep]


def build_demo(root: Path) -> OfflineDemo:
    case = next(
        json.loads(line)
        for line in (
            root / "evaluation" / "datasets" / "v1" / "test_cases_v1.jsonl"
        ).read_text("utf-8").splitlines()
        if json.loads(line)["case_id"] == "l4-001"
    )
    n05_rows = [
        json.loads(line)
        for line in (
            root
            / "evaluation"
            / "reports"
            / "n05_multi_agent_ablation_v1"
            / "case_scores.jsonl"
        ).read_text("utf-8").splitlines()
        if line.strip()
    ]
    full = next(
        item
        for item in n05_rows
        if item["case_id"] == "l4-001" and item["system_id"] == "full_system"
    )
    citations = [
        {
            "evidence_id": item["evidence_id"],
            "paper_id": item["paper_id"],
            "page": item["page_number"],
            "section": item["section"],
        }
        for item in case["required_evidence"]
    ]
    return OfflineDemo(
        scenario="L4 multi-paper comparison evidence tour",
        policy_notice=(
            "The production route remains Safe RAG. Dynamic Planner and Multi-Agent "
            "are demonstrated as bounded experimental evidence because M06/N05 are NO-GO."
        ),
        steps=[
            DemoStep(
                sequence=1,
                kind="route",
                title="Route complex request without silently promoting experiments",
                truth_class="integration_real",
                source_artifact="evaluation/reports/p01_runtime_integration_v1/report.json",
                data={
                    "production_default": "safe_rag",
                    "dynamic_planner": "opt_in_no_go",
                    "multi_agent": "opt_in_no_go",
                    "cascade": "unavailable_o_skipped",
                },
            ),
            DemoStep(
                sequence=2,
                kind="plan_change",
                title="Show bounded Plan state transition",
                truth_class="unit_fixture",
                source_artifact="tests/test_m05_dynamic_executor.py",
                data={
                    "from_version": 1,
                    "to_version": 2,
                    "trigger": "insufficient_evidence",
                    "max_replans": 2,
                    "claim_boundary": "mechanism evidence only",
                },
            ),
            DemoStep(
                sequence=3,
                kind="agent_roles",
                title="Replay the bounded collaboration roles",
                truth_class="offline_real_model",
                source_artifact="evaluation/reports/n05_multi_agent_ablation_v1/report.json",
                data={
                    "roles": ["paper_reader", "evidence", "critic", "writer", "verifier"],
                    "depth": 1,
                    "calls_per_case": 5,
                    "promotion_decision": "NO-GO",
                },
            ),
            DemoStep(
                sequence=4,
                kind="citations",
                title="Inspect Gold evidence IDs and page provenance",
                truth_class="human_review",
                source_artifact="evaluation/datasets/v1/test_cases_v1.jsonl",
                data={"case_id": "l4-001", "evidence_count": len(citations), "items": citations},
            ),
            DemoStep(
                sequence=5,
                kind="verifier",
                title="Inspect the frozen Full-System quality outcome",
                truth_class="offline_real_model",
                source_artifact="evaluation/reports/n05_multi_agent_ablation_v1/case_scores.jsonl",
                data={
                    "task_success": full["task_success"],
                    "claim_support": full["claim_support_rate"],
                    "omission_rate": full["omission_rate"],
                    "negative_result_visible": True,
                },
            ),
            DemoStep(
                sequence=6,
                kind="metrics",
                title="Close with measured Token and latency",
                truth_class="offline_real_model",
                source_artifact="evaluation/reports/n05_multi_agent_ablation_v1/case_scores.jsonl",
                data={
                    "total_tokens": full["total_tokens"],
                    "latency_ms": full["latency_ms"],
                    "system_id": full["system_id"],
                    "report": "evaluation/reports/p04_final_v1/report.json",
                },
            ),
        ],
    )


def write_demo(demo: OfflineDemo, output: Path) -> dict[str, Path]:
    output.mkdir(parents=True, exist_ok=True)
    json_path = output / "demo.json"
    markdown_path = output / "demo.md"
    json_path.write_text(demo.model_dump_json(indent=2) + "\n", encoding="utf-8")
    lines = [
        "# PaperAgent Offline Evidence Demo",
        "",
        f"> {demo.policy_notice}",
        "",
    ]
    for step in demo.steps:
        lines.extend(
            [
                f"## {step.sequence}. {step.title}",
                "",
                f"Truth class: `{step.truth_class}`; source: `{step.source_artifact}`.",
                "",
                "```json",
                json.dumps(step.data, ensure_ascii=False, indent=2, sort_keys=True),
                "```",
                "",
            ]
        )
    markdown_path.write_text("\n".join(lines), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    paths = write_demo(
        build_demo(root), root / "evaluation" / "reports" / "p05_demo_v1"
    )
    print(paths["markdown"].read_text("utf-8"))


if __name__ == "__main__":
    main()
