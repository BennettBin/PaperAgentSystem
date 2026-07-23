"""Build the public P03 read model from frozen L05 case-score rows."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evaluation.dashboard import DashboardCase, PublicTraceEvent


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-scores", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--system-id", required=True)
    parser.add_argument("--report-version", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--source-format", choices=("l05", "n05"), default="l05")
    parser.add_argument("--expected-rows", type=int, default=300)
    parser.add_argument("--model-calls", type=int, default=1)
    parser.add_argument("--four-b-calls", type=int, default=1)
    parser.add_argument("--append", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    dataset = {
        item["case_id"]: item
        for line in args.dataset.read_text("utf-8").splitlines()
        if line.strip()
        for item in [json.loads(line)]
    }
    rows = []
    for line in args.case_scores.read_text("utf-8").splitlines():
        if not line.strip():
            continue
        score = json.loads(line)
        if score["system_id"] != args.system_id:
            continue
        case = dataset[score["case_id"]]
        status = "completed" if score["task_success"] else "failed"
        is_n05 = args.source_format == "n05"
        rows.append(
            DashboardCase(
                report_version=args.report_version,
                case_id=score["case_id"],
                system_id=score["system_id"],
                task_family=case["task_family"],
                difficulty=case["difficulty"],
                language=case["language"],
                model=args.model,
                error_category=None if is_n05 else score["error_category"],
                task_success=score["task_success"],
                claim_support=score["claim_support_rate"] if is_n05 else None,
                input_tokens=score["total_tokens"] if is_n05 else score["input_tokens"],
                output_tokens=0 if is_n05 else score["output_tokens"],
                model_calls=args.model_calls if is_n05 else score["model_calls"],
                four_b_calls=args.four_b_calls if is_n05 else score["four_b_calls"],
                latency_ms=score["latency_ms"],
                monetary_cost=0.0,
                public_trace=[
                    PublicTraceEvent(
                        kind="evaluation_result",
                        title=(
                            "multi-agent quality evaluation"
                            if is_n05
                            else score["error_category"] or "task completed"
                        ),
                        status=status,
                    )
                ],
            )
        )
    if len(rows) != args.expected_rows:
        raise ValueError(
            f"expected {args.expected_rows} rows for one frozen system, got {len(rows)}"
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    serialized = "\n".join(item.model_dump_json() for item in rows) + "\n"
    if args.append and args.output.exists():
        with args.output.open("a", encoding="utf-8") as handle:
            handle.write(serialized)
    else:
        args.output.write_text(serialized, encoding="utf-8")


if __name__ == "__main__":
    main()
