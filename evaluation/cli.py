"""Command-line entry point for selected automated evaluations."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from evaluation.builtin import built_in_evaluators
from evaluation.metadata import discover_metadata
from evaluation.runner import EvaluationRunner
from evaluation.schema import EvaluationSuite


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run PaperAgent evaluation suites")
    parser.add_argument(
        "--suite",
        action="append",
        choices=[suite.value for suite in EvaluationSuite] + ["all"],
        default=[],
        help="Evaluation suite to run; repeat to select multiple suites",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("evaluation/reports/latest.json"),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    selected_values = args.suite or ["all"]
    selected = (
        list(EvaluationSuite)
        if "all" in selected_values
        else [EvaluationSuite(value) for value in selected_values]
    )
    report = EvaluationRunner(built_in_evaluators(root)).run(
        selected,
        metadata=discover_metadata(root),
    )
    output = args.output if args.output.is_absolute() else root / args.output
    report.write_json(output)
    print(f"evaluation report: {output}")
    return 0 if report.passed else 1
