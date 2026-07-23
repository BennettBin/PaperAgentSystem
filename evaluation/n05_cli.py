"""Run resumable real-model N05 multi-Agent ablation and freeze its report."""

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
    PageRecord,
    _score_case,
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
from evaluation.metadata import discover_metadata
from evaluation.n05_multi_agent_ablation import (
    MultiAgentAblationExecutor,
    N05CaseScore,
    N05Stage,
    build_n05_report,
)


def _parser() -> argparse.ArgumentParser:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Run N05 multi-Agent ablation")
    parser.add_argument("--dataset", type=Path, default=root / "evaluation/datasets/v1/test_cases_v1.jsonl")
    parser.add_argument("--documents", type=Path, default=root / "evaluation/datasets/v1/documents_v1.jsonl")
    parser.add_argument("--frozen-scores", type=Path, default=root / "evaluation/reports/l05_baselines_v1/case_scores.jsonl")
    parser.add_argument("--checkpoint", type=Path, default=root / "runtime/scratch/n05_checkpoints")
    parser.add_argument("--output", type=Path, default=root / "evaluation/reports/n05_multi_agent_ablation_v1")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--seed", type=int, default=20260721)
    parser.add_argument("--ollama", default="http://localhost:11434")
    parser.add_argument("--model", default="qwen3.5:4b")
    parser.add_argument("--allow-real-model", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.allow_real_model:
        raise SystemExit("--allow-real-model is required")
    cases, by_id = _load_cases(args.dataset, args.limit)
    version = _model_version(args.ollama, args.model)
    metadata = discover_metadata(Path(__file__).resolve().parents[1])
    executor = MultiAgentAblationExecutor(
        gateway=OllamaRealModelGateway(f"{args.ollama.rstrip('/')}/v1"),
        retriever=InMemoryHybridRetriever(load_page_records(args.documents)),
        model=args.model,
        model_version=version,
    )
    config = ExperimentRunConfig(
        run_id=f"n05-progressive-{len(cases)}-v1",
        system_id="n05-progressive-pipeline",
        dataset_version="paperagent-eval-v1-l4-l5",
        seed=args.seed,
        concurrency=args.concurrency,
        max_attempts=2,
        checkpoint_dir=args.checkpoint,
        budget=BudgetLimit(
            max_cases=len(cases),
            max_model_calls=len(cases) * 5,
            max_total_tokens=sum(case.reserved_total_tokens for case in cases),
        ),
        real_model=True,
        truth_class=EvaluationTruthClass.OFFLINE_REAL_MODEL,
        metadata={
            "model": args.model,
            "model_version": version,
            "role_prompts": "n05-roles-v1",
            "max_model_calls_per_case": 5,
            "same_max_token_budget": True,
            "commit": metadata.commit,
            "git_dirty": metadata.config.get("git_dirty"),
        },
    )
    results = ExperimentRunner(executor).run(cases, config)
    rows = _single_agent_rows(args.frozen_scores, set(by_id))
    for result in results:
        case = by_id[result.case_id]
        hits = [PageRecord.model_validate(item) for item in result.output["hits"]]
        for stage in N05Stage:
            payload = result.output["stages"][stage.value]
            call_count = int(result.output["stage_call_counts"][stage.value])
            calls = result.model_calls[:call_count]
            score = _score_case(case, payload["answer"], payload["citations"], hits)
            rows.append(
                N05CaseScore(
                    case_id=case.case_id,
                    system_id=stage.value,
                    task_success=bool(score["task_success"]),
                    claim_support_rate=float(score["citation_recall"]),
                    omission_rate=1 - float(score["citation_recall"]),
                    total_tokens=sum(call.total_tokens for call in calls),
                    latency_ms=sum(call.latency_ms for call in calls),
                    severe_unsupported_rate=_severe_unsupported_rate(payload, hits),
                    conflict_recall=None,
                )
            )
    args.output.mkdir(parents=True, exist_ok=True)
    _write_jsonl(args.output / "case_scores.jsonl", rows)
    report = build_n05_report(rows, truth_class="offline_real_model")
    report["run_metadata"] = {
        "model": args.model,
        "model_version": version,
        "case_count": len(cases),
        "completed_candidate_cases": len(results),
        "same_paper_set": True,
        "same_model": True,
        "same_max_token_budget": True,
        "gold_used_only_after_execution": True,
        "role_calls_per_case": 5,
    }
    _write_json(args.output / "report.json", report)
    _write_markdown(args.output / "report.md", report)
    _write_manifest(args.output)
    return 0 if report["all_gates_passed"] else 2


def _load_cases(
    path: Path, limit: int | None
) -> tuple[list[ExperimentCase], dict[str, EvaluationCase]]:
    selected: list[ExperimentCase] = []
    by_id: dict[str, EvaluationCase] = {}
    for line in path.read_text("utf-8").splitlines():
        case = EvaluationCase.model_validate_json(line)
        if case.difficulty.value not in {"L4", "L5"}:
            continue
        by_id[case.case_id] = case
        selected.append(
            ExperimentCase(
                case_id=case.case_id,
                payload=case.model_dump(mode="json"),
                reserved_model_calls=5,
                reserved_total_tokens=(
                    case.resource_budget.max_input_tokens
                    + case.resource_budget.max_output_tokens
                ),
            )
        )
        if limit is not None and len(selected) >= limit:
            break
    if not selected:
        raise ValueError("N05 selected no L4/L5 cases")
    return selected, by_id


def _single_agent_rows(path: Path, case_ids: set[str]) -> list[N05CaseScore]:
    rows: list[N05CaseScore] = []
    for line in path.read_text("utf-8").splitlines():
        raw = json.loads(line)
        if raw["system_id"] != "b3_full_4b" or raw["case_id"] not in case_ids:
            continue
        support = float(raw["citation_recall"])
        rows.append(
            N05CaseScore(
                case_id=raw["case_id"],
                system_id="single_agent",
                task_success=bool(raw["task_success"]),
                claim_support_rate=support,
                omission_rate=1 - support,
                total_tokens=int(raw["input_tokens"]) + int(raw["output_tokens"]),
                latency_ms=int(raw["latency_ms"]),
            )
        )
    return rows


def _severe_unsupported_rate(payload: dict[str, Any], hits: list[PageRecord]) -> float:
    claims = payload.get("claims", [])
    if not isinstance(claims, list) or not claims:
        return 0.0 if payload.get("citations") else 1.0
    valid = {hit.evidence_id for hit in hits}
    severe = 0
    for claim in claims:
        if not isinstance(claim, dict):
            severe += 1
            continue
        evidence = claim.get("evidence_ids", [])
        supported = isinstance(evidence, list) and bool(valid & {str(item) for item in evidence})
        if not supported and not bool(claim.get("inferred", False)):
            severe += 1
    return severe / len(claims)


def _model_version(endpoint: str, model: str) -> str:
    with urlopen(f"{endpoint.rstrip('/')}/api/tags", timeout=15) as response:
        payload: Any = json.loads(response.read().decode("utf-8"))
    for item in payload.get("models", []):
        if item.get("name") == model and item.get("digest"):
            return f"sha256:{item['digest']}"
    raise ValueError(f"required real Ollama model is unavailable: {model}")


def _write_json(path: Path, payload: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", "utf-8"
    )
    temporary.replace(path)


def _write_jsonl(path: Path, rows: list[N05CaseScore]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        "".join(
            json.dumps(row.model_dump(mode="json"), ensure_ascii=False, sort_keys=True) + "\n"
            for row in sorted(rows, key=lambda item: (item.system_id, item.case_id))
        ),
        "utf-8",
    )
    temporary.replace(path)


def _write_markdown(path: Path, report: dict[str, Any]) -> None:
    metrics = report["metrics"]
    lines = [
        "# N05 multi-Agent ablation",
        "",
        f"Truth class: `{report['truth_class']}`. Decision: "
        f"`{'GO' if report['all_gates_passed'] else 'NO-GO'}`.",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Paired cases | {metrics['paired_case_count']} |",
        f"| Task Success delta | {metrics['task_success_delta']:.4f} |",
        f"| Claim Support delta | {metrics['claim_support_delta']:.4f} |",
        f"| Total Token increase | {metrics['total_token_increase']} |",
        f"| Token/success increase | {metrics['token_per_success_increase']} |",
        f"| Conflict Recall delta | {metrics['conflict_recall_delta']} |",
        f"| Severe unsupported reduction | {metrics['severe_unsupported_reduction']} |",
        "",
        "| Gate | Passed |",
        "|---|---|",
    ]
    lines.extend(
        f"| {name} | {'yes' if passed else 'no'} |"
        for name, passed in sorted(report["gates"].items())
    )
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {item}" for item in report["limitations"])
    path.write_text("\n".join(lines) + "\n", "utf-8")


def _write_manifest(output: Path) -> None:
    artifacts = [output / "case_scores.jsonl", output / "report.json", output / "report.md"]
    _write_json(
        output / "frozen_manifest.json",
        {
            "schema_version": "1.0",
            "artifacts": {
                path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in artifacts
            },
        },
    )


if __name__ == "__main__":
    raise SystemExit(main())
