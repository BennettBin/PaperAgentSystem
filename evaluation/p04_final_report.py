"""Build the final evidence report from frozen L05/M06/N05 artifacts."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field

from evaluation.metrics.statistics import (
    ConfidenceInterval,
    bootstrap_mean_ci,
    bootstrap_statistic_ci,
    percentile,
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PublicMetric(_StrictModel):
    value: float | None
    numerator: float | None
    denominator: int = Field(ge=0)
    sample_count: int = Field(ge=0)
    unit: str
    confidence_interval: ConfidenceInterval | None
    source_artifact: str
    unavailable_reason: str | None = None


class FinalSystem(_StrictModel):
    system_id: str
    sample_count: int
    metrics: dict[str, PublicMetric]
    slices: dict[str, dict[str, "SliceSummary"]]
    reused_from: str | None = None
    truth_class: str = "offline_real_model"


class SliceSummary(_StrictModel):
    sample_count: int
    metrics: dict[str, PublicMetric]


class AblationResult(_StrictModel):
    name: str
    decision: str
    sample_count: int
    primary_metric: PublicMetric | None
    source_artifact: str | None
    unavailable_reason: str | None = None


class HumanAuditEvidence(_StrictModel):
    sample_count: int
    population: int
    sample_rate: float
    scope: str
    agreement: float
    source_artifact: str


class P04FinalReport(_StrictModel):
    schema_version: str = "1.0"
    report_version: str = "p04-final-v1"
    systems: dict[str, FinalSystem]
    ablations: dict[str, AblationResult]
    comparisons_to_b0: list[dict[str, object]]
    human_audit: HumanAuditEvidence
    failures: list[dict[str, object]]
    limitations: list[str]
    reproducibility: dict[str, object]


def build_p04_report(root: Path) -> P04FinalReport:
    l05_root = root / "evaluation" / "reports" / "l05_baselines_v1"
    l05_report = _json(l05_root / "baseline_report.json")
    rows = [
        json.loads(line)
        for line in (l05_root / "case_scores.jsonl").read_text("utf-8").splitlines()
        if line.strip()
    ]
    dataset_rows = [
        json.loads(line)
        for line in (
            root / "evaluation" / "datasets" / "v1" / "test_cases_v1.jsonl"
        ).read_text("utf-8").splitlines()
        if line.strip()
    ]
    language_by_case = {item["case_id"]: item["language"] for item in dataset_rows}
    for row in rows:
        row["language"] = language_by_case[row["case_id"]]
    systems: dict[str, FinalSystem] = {}
    for system_id in (
        "b0_vanilla_rag",
        "b1_fixed_workflow",
        "b2_bounded_react",
        "b3_full_4b",
    ):
        selected = [item for item in rows if item["system_id"] == system_id]
        systems[system_id] = _system(system_id, selected)
    systems["production_safe_path"] = systems["b1_fixed_workflow"].model_copy(
        update={"system_id": "production_safe_path", "reused_from": "b1_fixed_workflow"}
    )

    m06_path = root / "evaluation" / "reports" / "m06_planner_ablation_v1" / "report.json"
    n05_path = root / "evaluation" / "reports" / "n05_multi_agent_ablation_v1" / "report.json"
    m06 = _json(m06_path)
    n05 = _json(n05_path)
    planner_ci = m06["metrics"]["task_success_delta_ci95"]
    planner_metric = PublicMetric(
        value=m06["metrics"]["task_success_delta"],
        numerator=None,
        denominator=180,
        sample_count=180,
        unit="paired_task_success_delta",
        confidence_interval=ConfidenceInterval.model_validate(planner_ci),
        source_artifact="evaluation/reports/m06_planner_ablation_v1/report.json",
    )
    multi_ci = n05["metrics"]["task_success_delta_ci"]
    multi_metric = PublicMetric(
        value=n05["metrics"]["task_success_delta"],
        numerator=None,
        denominator=n05["metrics"]["paired_case_count"],
        sample_count=n05["metrics"]["paired_case_count"],
        unit="paired_task_success_delta",
        confidence_interval=ConfidenceInterval(
            estimate=n05["metrics"]["task_success_delta"],
            lower=multi_ci["lower"],
            upper=multi_ci["upper"],
            confidence=0.95,
            method="paired_percentile_bootstrap",
            samples=2000,
            seed=20260722,
        ),
        source_artifact="evaluation/reports/n05_multi_agent_ablation_v1/report.json",
    )
    unavailable = "Stage O was explicitly skipped by the user; no effect estimate exists."
    ablations = {
        "planner": AblationResult(
            name="planner",
            decision="no_go",
            sample_count=180,
            primary_metric=planner_metric,
            source_artifact="evaluation/reports/m06_planner_ablation_v1/report.json",
        ),
        "multi_agent": AblationResult(
            name="multi_agent",
            decision="no_go",
            sample_count=90,
            primary_metric=multi_metric,
            source_artifact="evaluation/reports/n05_multi_agent_ablation_v1/report.json",
        ),
        "sft": AblationResult(
            name="sft", decision="unavailable", sample_count=0,
            primary_metric=None, source_artifact=None, unavailable_reason=unavailable,
        ),
        "cascade": AblationResult(
            name="cascade", decision="unavailable", sample_count=0,
            primary_metric=None, source_artifact=None, unavailable_reason=unavailable,
        ),
    }
    audit = _json(root / "evaluation" / "datasets" / "v1" / "annotation_agreement_v1.json")
    environment = _json(
        root / "evaluation" / "manifests" / "l00_environment_2026-07-21.json"
    )
    failures = [
        {"category": category, "count": count, "source_artifact": "evaluation/reports/l05_baselines_v1/case_scores.jsonl"}
        for category, count in Counter(
            item["error_category"] for item in rows if item["error_category"]
        ).most_common(5)
    ]
    return P04FinalReport(
        systems=systems,
        ablations=ablations,
        comparisons_to_b0=l05_report["comparisons_to_b0"],
        human_audit=HumanAuditEvidence(
            sample_count=audit["sample_size"],
            population=300,
            sample_rate=audit["sample_rate"],
            scope="dataset_answer_type_gold_not_final_output",
            agreement=audit["cohen_kappa"],
            source_artifact="evaluation/datasets/v1/annotation_agreement_v1.json",
        ),
        failures=failures,
        limitations=[
            "All B0-B3 Task Success confidence intervals overlap; no baseline beats B0 significantly.",
            "Planner and Multi-Agent are effect No-Go and remain non-default.",
            "SFT and Cascade are unavailable because Stage O was explicitly skipped.",
            "The 10% human audit validates dataset answer-type Gold, not final generated outputs.",
            "Local monetary cost is zero-valued accounting and excludes electricity/hardware amortization.",
        ],
        reproducibility={
            "dataset_version": l05_report["dataset_version"],
            "commit": l05_report["commit"],
            "hardware": environment["hardware"],
            "models": environment["ollama_models_in_scope"],
            "commands": [
                "python -m evaluation.l05_cli --help",
                "python -m evaluation.m06_cli --help",
                "python -m evaluation.n05_cli --help",
                "python -m evaluation.p04_final_report",
            ],
            "source_manifest": "evaluation/reports/l05_baselines_v1/frozen_manifest.json",
        },
    )


def _system(system_id: str, rows: list[dict[str, Any]]) -> FinalSystem:
    n = len(rows)
    if n != 300:
        raise ValueError(f"{system_id} requires 300 frozen rows, got {n}")
    source = "evaluation/reports/l05_baselines_v1/case_scores.jsonl"
    success = [float(bool(item["task_success"])) for item in rows]
    citation = [float(item["citation_recall"]) for item in rows]
    correctness = [float(item["answer_correctness"]) for item in rows]
    tokens = [float(item["input_tokens"]) + float(item["output_tokens"]) for item in rows]
    call_rates = [
        float(item["four_b_calls"]) / float(item["model_calls"])
        if int(item["model_calls"]) else 0.0
        for item in rows
    ]
    latencies = [float(item["latency_ms"]) for item in rows]
    passed = int(sum(success))
    slices: dict[str, dict[str, SliceSummary]] = {}
    for dimension in ("difficulty", "task_family", "language"):
        slices[dimension] = {}
        for value in sorted({str(item[dimension]) for item in rows}):
            selected = [item for item in rows if str(item[dimension]) == value]
            selected_success = [float(bool(item["task_success"])) for item in selected]
            selected_citation = [float(item["citation_recall"]) for item in selected]
            slices[dimension][value] = SliceSummary(
                sample_count=len(selected),
                metrics={
                    "task_success": _mean_metric(
                        selected_success, sum(selected_success), len(selected),
                        "ratio", source, 10 + len(slices[dimension]),
                    ),
                    "citation_recall": _mean_metric(
                        selected_citation, sum(selected_citation), len(selected),
                        "ratio", source, 30 + len(slices[dimension]),
                    ),
                },
            )
    return FinalSystem(
        system_id=system_id,
        sample_count=n,
        slices=slices,
        metrics={
            "task_success": _mean_metric(success, sum(success), n, "ratio", source, 1),
            "answer_correctness": _mean_metric(
                correctness, sum(correctness), n, "ratio", source, 6
            ),
            "citation_recall": _mean_metric(citation, sum(citation), n, "ratio", source, 2),
            "mean_total_tokens": _mean_metric(tokens, sum(tokens), n, "tokens", source, 3),
            "four_b_call_rate": _mean_metric(call_rates, sum(call_rates), n, "ratio", source, 4),
            "p95_latency_ms": PublicMetric(
                value=percentile(latencies, 0.95), numerator=None, denominator=n,
                sample_count=n, unit="milliseconds",
                confidence_interval=bootstrap_statistic_ci(
                    latencies, statistic=lambda values: percentile(values, 0.95),
                    samples=500, seed=20260725,
                ),
                source_artifact=source,
            ),
            "cost_per_success": PublicMetric(
                value=0.0 if passed else None, numerator=0.0, denominator=passed,
                sample_count=n, unit="local_monetary_cost_per_success",
                confidence_interval=(
                    ConfidenceInterval(
                        estimate=0.0, lower=0.0, upper=0.0, confidence=0.95,
                        method="exact_local_zero", samples=1, seed=0,
                    ) if passed else None
                ),
                source_artifact=source,
                unavailable_reason=None if passed else "no successful denominator",
            ),
        },
    )


def _mean_metric(
    values: list[float], numerator: float, denominator: int, unit: str,
    source: str, seed_offset: int,
) -> PublicMetric:
    return PublicMetric(
        value=sum(values) / len(values), numerator=numerator, denominator=denominator,
        sample_count=len(values), unit=unit,
        confidence_interval=bootstrap_mean_ci(
            values, samples=500, seed=20260720 + seed_offset
        ),
        source_artifact=source,
    )


def write_p04_report(report: P04FinalReport, output: Path) -> dict[str, Path]:
    output.mkdir(parents=True, exist_ok=True)
    json_path = output / "report.json"
    markdown_path = output / "report.md"
    json_path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    lines = [
        "# PaperAgent Final Evaluation Report", "",
        "## B0-B3 and production-safe policy", "",
        "| System | N | Task Success (95% CI) | Citation Recall | Mean Token | P95 ms |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for system in report.systems.values():
        task = system.metrics["task_success"]
        citation = system.metrics["citation_recall"]
        tokens = system.metrics["mean_total_tokens"]
        latency = system.metrics["p95_latency_ms"]
        ci = task.confidence_interval
        if ci is None or task.value is None or citation.value is None or tokens.value is None or latency.value is None:
            raise ValueError(f"public metric unexpectedly unavailable for {system.system_id}")
        lines.append(
            f"| {system.system_id} | {system.sample_count} | {task.value:.4f} "
            f"[{ci.lower:.4f}, {ci.upper:.4f}] | {citation.value:.4f} | "
            f"{tokens.value:.1f} | {latency.value:.1f} |"
        )
    lines.extend(["", "## Ablations", ""])
    for item in report.ablations.values():
        lines.append(
            f"- {item.name}: **{item.decision.upper().replace('_', '-')}**; "
            f"{item.unavailable_reason or item.source_artifact}."
        )
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {item}" for item in report.limitations)
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}


def _json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return cast(dict[str, Any], payload)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    write_p04_report(
        build_p04_report(root),
        root / "evaluation" / "reports" / "p04_final_v1",
    )


if __name__ == "__main__":
    main()
