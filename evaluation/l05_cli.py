"""Run and freeze all four L05 baselines with local real Model Profiles."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from evaluation.baseline_evaluation import (
    BaselineCaseScore,
    InMemoryHybridRetriever,
    OfflineBaselineExecutor,
    OllamaRealModelGateway,
    build_l05_report,
    classify_baseline_failure,
    load_page_records,
)
from evaluation.baselines import EvaluationTruthClass, load_baseline_by_id, load_baselines
from evaluation.datasets.schema import EvaluationCase
from evaluation.experiments import (
    BudgetLimit,
    ExperimentCase,
    ExperimentRunConfig,
    ExperimentRunner,
    TraceReplay,
    build_report,
    write_report_bundle,
)
from evaluation.metadata import discover_metadata


def _parser() -> argparse.ArgumentParser:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Run L05 frozen real-model baselines")
    parser.add_argument("--dataset", type=Path, default=root / "evaluation/datasets/v1/test_cases_v1.jsonl")
    parser.add_argument("--documents", type=Path, default=root / "evaluation/datasets/v1/documents_v1.jsonl")
    parser.add_argument("--baseline-dir", type=Path, default=root / "evaluation/baselines")
    parser.add_argument("--checkpoint", type=Path, default=root / "runtime/scratch/l05_checkpoints")
    parser.add_argument("--output", type=Path, default=root / "evaluation/reports/l05_baselines_v1")
    parser.add_argument("--baseline", action="append", default=[])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--seed", type=int, default=20260721)
    parser.add_argument("--ollama", default="http://localhost:11434")
    parser.add_argument("--small-model", default="qwen3:1.7b")
    parser.add_argument("--large-model", default="qwen3.5:4b")
    parser.add_argument("--allow-real-model", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.allow_real_model:
        raise SystemExit("--allow-real-model is required; this run incurs local model compute")
    root = Path(__file__).resolve().parents[1]
    selected_ids = args.baseline or [item.baseline_id for item in load_baselines(args.baseline_dir)]
    cases = _load_cases(args.dataset, args.limit)
    retriever = InMemoryHybridRetriever(load_page_records(args.documents))
    versions = _model_versions(args.ollama, {args.small_model, args.large_model})
    metadata = discover_metadata(root)
    manifest = json.loads((args.dataset.parent / "dataset_manifest_v1.json").read_text("utf-8"))
    all_results = []
    baseline_metadata: dict[str, Any] = {}
    case_by_id = {case.case_id: EvaluationCase.model_validate(case.payload) for case in cases}
    for baseline_id in selected_ids:
        baseline = load_baseline_by_id(args.baseline_dir, baseline_id)
        baseline_metadata[baseline.baseline_id] = {
            "config_hash": baseline.config_hash,
            "prompt_versions": baseline.prompt_versions,
        }
        executor = OfflineBaselineExecutor(
            baseline=baseline,
            gateway=OllamaRealModelGateway(f"{args.ollama.rstrip('/')}/v1"),
            retriever=retriever,
            small_model=args.small_model,
            large_model=args.large_model,
            model_versions=versions,
        )
        config = ExperimentRunConfig(
            run_id=f"l05-{baseline.baseline_id}-v1",
            system_id=baseline.baseline_id,
            dataset_version=manifest["dataset_version"],
            seed=args.seed,
            concurrency=args.concurrency,
            max_attempts=2,
            checkpoint_dir=args.checkpoint,
            budget=BudgetLimit(
                max_cases=len(cases),
                max_model_calls=sum(case.reserved_model_calls for case in cases),
                max_total_tokens=sum(case.reserved_total_tokens for case in cases),
            ),
            real_model=True,
            truth_class=EvaluationTruthClass.OFFLINE_REAL_MODEL,
            metadata={
                "baseline_hash": baseline.config_hash,
                "model_versions": versions,
                "prompt_versions": baseline.prompt_versions,
                "dataset_cases_sha256": manifest["cases_sha256"],
                "retriever": "in-memory-production-equivalent-hybrid-v1",
                "commit": metadata.commit,
                "git_dirty": metadata.config.get("git_dirty"),
            },
        )
        results = ExperimentRunner(executor).run(cases, config)
        all_results.extend(results)
        write_report_bundle(
            build_report(
                results,
                dataset_version=config.dataset_version,
                truth_class=config.truth_class,
            ),
            args.output / baseline.baseline_id,
        )
        _write_replay_index(results, args.output / baseline.baseline_id / "replay_index.json")

    scores = [_case_score(result, case_by_id[result.case_id]) for result in all_results]
    report = build_l05_report(
        scores,
        dataset_version=manifest["dataset_version"],
        commit=metadata.commit,
        run_metadata={
            "truth_evidence": "ollama_real_model_usage",
            "model_versions": versions,
            "baselines": baseline_metadata,
            "dataset_cases_sha256": manifest["cases_sha256"],
            "retriever": "in-memory-production-equivalent-hybrid-v1",
            "seed": args.seed,
            "git_dirty": metadata.config.get("git_dirty"),
        },
    )
    _write_outputs(report, scores, args.output)
    expected_cases = len(cases) * len(selected_ids)
    return 0 if len(all_results) == expected_cases else 1


def _load_cases(path: Path, limit: int | None) -> list[ExperimentCase]:
    result = []
    for line in path.read_text("utf-8").splitlines():
        if not line.strip():
            continue
        case = EvaluationCase.model_validate_json(line)
        result.append(
            ExperimentCase(
                case_id=case.case_id,
                payload=case.model_dump(mode="json"),
                reserved_model_calls=case.resource_budget.max_model_calls,
                reserved_total_tokens=(
                    case.resource_budget.max_input_tokens + case.resource_budget.max_output_tokens
                ),
            )
        )
        if limit is not None and len(result) >= limit:
            break
    if not result:
        raise ValueError("L05 dataset is empty")
    return result


def _model_versions(endpoint: str, required: set[str]) -> dict[str, str]:
    with urlopen(f"{endpoint.rstrip('/')}/api/tags", timeout=15) as response:
        payload: Any = json.loads(response.read().decode("utf-8"))
    versions = {
        str(item["name"]): f"sha256:{item['digest']}"
        for item in payload.get("models", [])
        if item.get("name") in required and item.get("digest")
    }
    missing = required - set(versions)
    if missing:
        raise ValueError(f"required real Ollama models are unavailable: {sorted(missing)}")
    return versions


def _case_score(result: Any, case: EvaluationCase) -> BaselineCaseScore:
    score = result.output.get(
        "score",
        {"task_success": False, "answer_correctness": 0.0, "citation_recall": 0.0},
    )
    error_category = classify_baseline_failure(
        case,
        task_success=bool(score["task_success"]),
        answer_correctness=float(score["answer_correctness"]),
        citation_recall=float(score["citation_recall"]),
        retrieved_count=len(result.output.get("retrieved", [])),
    )
    return BaselineCaseScore(
        case_id=result.case_id,
        system_id=result.system_id,
        difficulty=case.difficulty.value,
        task_family=case.task_family,
        task_success=bool(score["task_success"]),
        answer_correctness=float(score["answer_correctness"]),
        citation_recall=float(score["citation_recall"]),
        latency_ms=int(
            result.output.get(
                "latency_ms", sum(call.latency_ms for call in result.model_calls)
            )
        ),
        input_tokens=sum(call.input_tokens for call in result.model_calls),
        output_tokens=sum(call.output_tokens for call in result.model_calls),
        model_calls=len(result.model_calls),
        four_b_calls=sum(call.model == "qwen3.5:4b" for call in result.model_calls),
        error_category=(
            "system" if not result.output.get("score") else error_category
        ),
    )


def _write_replay_index(results: list[Any], path: Path) -> None:
    replay = TraceReplay.from_results(results)
    payload = {
        result.case_id: {
            "task_id": result.task_id,
            "timeline_events": len(replay.by_case_id(result.case_id).timeline),
        }
        for result in results
    }
    _write_json(path, payload)


def _write_outputs(report: Any, scores: list[BaselineCaseScore], output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    _write_json(output / "baseline_report.json", report.model_dump(mode="json"))
    (output / "case_scores.jsonl").write_text(
        "".join(
            json.dumps(score.model_dump(mode="json"), ensure_ascii=False, sort_keys=True) + "\n"
            for score in sorted(scores, key=lambda item: (item.system_id, item.case_id))
        ),
        encoding="utf-8",
    )
    dashboard = {
        "schema_version": report.schema_version,
        "truth_class": report.truth_class.value,
        "systems": [system.model_dump(mode="json") for system in report.systems],
        "comparisons_to_b0": [item.model_dump(mode="json") for item in report.comparisons_to_b0],
        "top_actionable_failures": report.top_actionable_failures,
        "success_gates": report.success_gates,
        "go_no_go": report.go_no_go,
    }
    _write_json(output / "dashboard.json", dashboard)
    lines = [
        "# L05 frozen baseline report",
        "",
        f"Truth class: `{report.truth_class.value}`; dataset: `{report.dataset_version}`.",
        "",
        "| System | Cases | Task success | Answer correctness | Citation recall | p50 ms | p95 ms | Tokens | 4B call rate |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for system in report.systems:
        lines.append(
            f"| {system.system_id} | {system.case_count} | {system.overall.task_success:.4f} | "
            f"{system.overall.answer_correctness:.4f} | {system.overall.citation_recall:.4f} | "
            f"{system.latency_p50_ms:.0f} | {system.latency_p95_ms:.0f} | "
            f"{system.input_tokens + system.output_tokens} | {system.four_b_call_rate:.4f} |"
        )
    lines.extend(["", "Top actionable failures: " + ", ".join(report.top_actionable_failures)])
    (output / "baseline_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    artifact_names = ["baseline_report.json", "baseline_report.md", "case_scores.jsonl", "dashboard.json"]
    _write_json(
        output / "frozen_manifest.json",
        {
            "schema_version": "1.0",
            "dataset_version": report.dataset_version,
            "truth_class": report.truth_class.value,
            "artifacts": {
                name: "sha256:" + hashlib.sha256((output / name).read_bytes()).hexdigest()
                for name in artifact_names
            },
            "run_metadata": report.run_metadata,
        },
    )


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
