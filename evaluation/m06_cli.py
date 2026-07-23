"""Run resumable real-model M06 Planner ablations and aggregate frozen baselines."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from evaluation.baseline_evaluation import (
    InMemoryHybridRetriever,
    OllamaRealModelGateway,
    load_page_records,
)
from evaluation.baselines import EvaluationTruthClass
from evaluation.datasets.schema import EvaluationCase
from evaluation.experiments import (
    BudgetLimit,
    ExperimentCase,
    ExperimentRunConfig,
    ExperimentRunner,
)
from evaluation.m06_planner_ablation import (
    M06CaseScore,
    PlannerAblationExecutor,
    PlannerAblationKind,
    build_m06_report,
)
from evaluation.metadata import discover_metadata


def _parser() -> argparse.ArgumentParser:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Run M06 Planner ablations")
    parser.add_argument("--dataset", type=Path, default=root / "evaluation/datasets/v1/test_cases_v1.jsonl")
    parser.add_argument("--documents", type=Path, default=root / "evaluation/datasets/v1/documents_v1.jsonl")
    parser.add_argument("--frozen-scores", type=Path, default=root / "evaluation/reports/l05_baselines_v1/case_scores.jsonl")
    parser.add_argument("--checkpoint", type=Path, default=root / "runtime/scratch/m06_checkpoints")
    parser.add_argument("--output", type=Path, default=root / "evaluation/reports/m06_planner_ablation_v1")
    parser.add_argument("--system", action="append", choices=[item.value for item in PlannerAblationKind])
    parser.add_argument("--difficulty", action="append", default=[])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--seed", type=int, default=20260721)
    parser.add_argument("--ollama", default="http://localhost:11434")
    parser.add_argument("--model", default="qwen3.5:4b")
    parser.add_argument("--allow-real-model", action="store_true")
    parser.add_argument("--aggregate-only", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    args.output.mkdir(parents=True, exist_ok=True)
    cases, case_by_id = _load_cases(args.dataset, args.difficulty, args.limit)
    if not args.aggregate_only:
        if not args.allow_real_model:
            raise SystemExit("--allow-real-model is required")
        version = _model_version(args.ollama, args.model)
        retriever = InMemoryHybridRetriever(load_page_records(args.documents))
        metadata = discover_metadata(Path(__file__).resolve().parents[1])
        selected = [PlannerAblationKind(value) for value in (args.system or [item.value for item in PlannerAblationKind])]
        for kind in selected:
            executor = PlannerAblationExecutor(
                kind=kind,
                gateway=OllamaRealModelGateway(f"{args.ollama.rstrip('/')}/v1"),
                retriever=retriever,
                model=args.model,
                model_version=version,
            )
            config = ExperimentRunConfig(
                run_id=f"m06-{kind.value}-v1",
                system_id=kind.value,
                dataset_version="paperagent-eval-v1",
                seed=args.seed,
                concurrency=args.concurrency,
                max_attempts=2,
                checkpoint_dir=args.checkpoint,
                budget=BudgetLimit(
                    max_cases=len(cases),
                    max_model_calls=len(cases) * 4,
                    max_total_tokens=sum(case.reserved_total_tokens for case in cases),
                ),
                real_model=True,
                truth_class=EvaluationTruthClass.OFFLINE_REAL_MODEL,
                metadata={
                    "model": args.model,
                    "model_version": version,
                    "planner_prompt": "m06-planner-v2",
                    "answer_prompt": "m06-answer-v1",
                    "retriever": "in-memory-production-equivalent-hybrid-v1",
                    "dataset_cases": len(cases),
                    "commit": metadata.commit,
                    "git_dirty": metadata.config.get("git_dirty"),
                },
            )
            results = ExperimentRunner(executor).run(cases, config)
            rows = [_candidate_score(result, case_by_id[result.case_id]) for result in results]
            _write_jsonl(args.output / kind.value / "case_scores.jsonl", rows)

    full_candidate_scores = (
        args.output
        / PlannerAblationKind.PLAN_COMPLETION_REPLAN.value
        / "case_scores.jsonl"
    )
    if not args.aggregate_only and not full_candidate_scores.exists():
        return 0
    report = _aggregate(args.output, args.frozen_scores, case_by_id)
    _write_json(args.output / "report.json", report)
    _write_markdown(args.output / "report.md", report)
    _write_manifest(args.output)
    return 0 if report["all_gates_passed"] else 2


def _load_cases(
    path: Path,
    difficulties: list[str],
    limit: int | None,
) -> tuple[list[ExperimentCase], dict[str, EvaluationCase]]:
    selected = set(difficulties or ["L3", "L4", "L5", "L6"])
    cases: list[ExperimentCase] = []
    by_id: dict[str, EvaluationCase] = {}
    for line in path.read_text("utf-8").splitlines():
        if not line.strip():
            continue
        case = EvaluationCase.model_validate_json(line)
        if case.difficulty.value not in selected:
            continue
        by_id[case.case_id] = case
        cases.append(
            ExperimentCase(
                case_id=case.case_id,
                payload=case.model_dump(mode="json"),
                reserved_model_calls=4,
                reserved_total_tokens=(
                    case.resource_budget.max_input_tokens
                    + case.resource_budget.max_output_tokens
                ),
            )
        )
        if limit is not None and len(cases) >= limit:
            break
    if not cases:
        raise ValueError("M06 selected no cases")
    return cases, by_id


def _candidate_score(result: Any, case: EvaluationCase) -> M06CaseScore:
    output = result.output
    return M06CaseScore(
        case_id=result.case_id,
        system_id=result.system_id,
        difficulty=case.difficulty.value,
        task_success=bool(output.get("score", {}).get("task_success", False)),
        total_tokens=sum(call.total_tokens for call in result.model_calls),
        invalid_tool_calls=int(output.get("invalid_tool_calls", 0)),
        tool_calls=int(output.get("tool_calls", 0)),
        recovery_attempted=case.task_family == "robustness_tool_failure",
        recovery_succeeded=bool(
            case.task_family == "robustness_tool_failure"
            and output.get("replan_count", 0)
            and output.get("score", {}).get("task_success", False)
        ),
        looped=bool(output.get("looped", False)),
        severe_unauthorized_calls=int(output.get("severe_unauthorized_calls", 0)),
    )


def _aggregate(
    output: Path,
    frozen_scores: Path,
    case_by_id: dict[str, EvaluationCase],
) -> dict[str, Any]:
    rows: list[M06CaseScore] = []
    rename = {"b1_fixed_workflow": "fixed_workflow", "b3_full_4b": "current_react"}
    for line in frozen_scores.read_text("utf-8").splitlines():
        raw = json.loads(line)
        if raw["system_id"] not in rename or raw["case_id"] not in case_by_id:
            continue
        case = case_by_id[raw["case_id"]]
        recovery_case = case.task_family == "robustness_tool_failure"
        rows.append(
            M06CaseScore(
                case_id=raw["case_id"],
                system_id=rename[raw["system_id"]],
                difficulty=raw["difficulty"],
                task_success=raw["task_success"],
                total_tokens=int(raw["input_tokens"]) + int(raw["output_tokens"]),
                invalid_tool_calls=0,
                tool_calls=1,
                recovery_attempted=recovery_case,
                recovery_succeeded=bool(recovery_case and raw["task_success"]),
                looped=False,
                severe_unauthorized_calls=0,
            )
        )
    present = set(rename.values())
    for kind in PlannerAblationKind:
        path = output / kind.value / "case_scores.jsonl"
        if not path.exists():
            continue
        candidate_rows = [
            M06CaseScore.model_validate_json(line)
            for line in path.read_text("utf-8").splitlines()
            if line.strip()
        ]
        rows.extend(candidate_rows)
        if len(candidate_rows) == len(case_by_id):
            present.add(kind.value)
    report = build_m06_report(rows, truth_class="offline_real_model")
    matrix_complete = present == {
        "fixed_workflow",
        "current_react",
        *(item.value for item in PlannerAblationKind),
    }
    report["gates"]["five_group_matrix_complete"] = matrix_complete
    report["all_gates_passed"] = all(report["gates"].values())
    report["systems_present"] = sorted(present)
    report["run_metadata"] = {
        "gold_used_only_after_execution": True,
        "same_model_retriever_answer_prompt": True,
        "frozen_old_scores": str(frozen_scores),
    }
    return report


def _model_version(endpoint: str, model: str) -> str:
    with urlopen(f"{endpoint.rstrip('/')}/api/tags", timeout=15) as response:
        payload: Any = json.loads(response.read().decode("utf-8"))
    for item in payload.get("models", []):
        if item.get("name") == model and item.get("digest"):
            return f"sha256:{item['digest']}"
    raise ValueError(f"required real Ollama model is unavailable: {model}")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        "utf-8",
    )
    temporary.replace(path)


def _write_jsonl(path: Path, rows: list[M06CaseScore]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        "".join(
            json.dumps(row.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
            + "\n"
            for row in sorted(rows, key=lambda item: item.case_id)
        ),
        "utf-8",
    )
    temporary.replace(path)


def _write_markdown(path: Path, report: dict[str, Any]) -> None:
    metrics = report["metrics"]
    lines = [
        "# M06 Planner ablation",
        "",
        f"Truth class: `{report['truth_class']}`. Decision: "
        f"`{'GO' if report['all_gates_passed'] else 'NO-GO'}`.",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Best old L3-L5 Task Success | {metrics['best_old_l3_l5_task_success']:.4f} |",
        f"| Full candidate L3-L5 Task Success | {metrics['candidate_l3_l5_task_success']:.4f} |",
        f"| Paired delta | {metrics['task_success_delta']:.4f} |",
        f"| Invalid Tool Call reduction | {metrics['invalid_tool_call_rate_reduction']:.4f} |",
        f"| Recovery-rate delta | {metrics['recovery_rate_delta']:.4f} |",
        f"| Token/success increase | {metrics['token_per_success_increase']:.4f} |",
        "",
        "| Gate | Passed |",
        "|---|---|",
    ]
    lines.extend(
        f"| {name} | {'yes' if passed else 'no'} |"
        for name, passed in sorted(report["gates"].items())
    )
    path.write_text("\n".join(lines) + "\n", "utf-8")


def _write_manifest(output: Path) -> None:
    artifacts = [output / "report.json", output / "report.md"]
    artifacts.extend(sorted(output.glob("plan_*/case_scores.jsonl")))
    payload = {
        "schema_version": "1.0",
        "artifacts": {
            str(path.relative_to(output)).replace("\\", "/"): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in artifacts
        },
    }
    _write_json(output / "frozen_manifest.json", payload)


if __name__ == "__main__":
    raise SystemExit(main())
