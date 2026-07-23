"""Separate entry points for CI smoke and explicitly authorized real-model runs."""

from __future__ import annotations

import argparse
import importlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

from evaluation.baselines import EvaluationTruthClass
from evaluation.experiments import (
    BudgetLimit,
    ExperimentCase,
    ExperimentExecutor,
    ExperimentResult,
    ExperimentRunConfig,
    ExperimentRunner,
    ModelCall,
    TraceEvent,
    build_report,
    write_report_bundle,
)


class ContractSmokeExecutor:
    """Deterministic contract executor; never represents model quality."""

    def execute(
        self, case: ExperimentCase, *, seed: int, attempt: int
    ) -> ExperimentResult:
        return ExperimentResult(
            case_id=case.case_id,
            task_id=f"smoke-{case.case_id}",
            system_id="contract-smoke",
            passed=True,
            model_calls=[
                ModelCall(
                    model="fake-contract-model",
                    profile="ci-smoke",
                    version="1",
                    input_tokens=0,
                    output_tokens=0,
                    latency_ms=0,
                )
            ],
            trace=[
                TraceEvent(
                    sequence=1,
                    kind="decision",
                    data={"seed": seed, "attempt": attempt, "contract_only": True},
                )
            ],
        )


def _common_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--dataset-version", default="l02-v1")
    parser.add_argument("--system-id", default="candidate")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--seed", type=int, default=20260721)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--max-attempts", type=int, default=2)
    parser.add_argument("--limit", type=int)
    return parser


def smoke_main(argv: Sequence[str] | None = None) -> int:
    parser = _common_parser("Run deterministic CI experiment smoke checks")
    args = parser.parse_args(argv)
    cases = _load_cases(args.dataset, limit=args.limit)
    return _run(args, cases, ContractSmokeExecutor(), real_model=False)


def real_main(argv: Sequence[str] | None = None) -> int:
    parser = _common_parser("Run an explicitly authorized offline real-model evaluation")
    parser.add_argument(
        "--executor-factory",
        required=True,
        help="Dotted factory in module:callable form; must return ExperimentExecutor.",
    )
    parser.add_argument(
        "--allow-real-model",
        action="store_true",
        help="Required acknowledgement that this command may incur model cost.",
    )
    args = parser.parse_args(argv)
    if not args.allow_real_model:
        parser.error("--allow-real-model is required")
    cases = _load_cases(args.dataset, limit=args.limit)
    executor = _load_executor(args.executor_factory)
    return _run(args, cases, executor, real_model=True)


def _run(
    args: argparse.Namespace,
    cases: list[ExperimentCase],
    executor: ExperimentExecutor,
    *,
    real_model: bool,
) -> int:
    config = ExperimentRunConfig(
        run_id=args.run_id,
        system_id=args.system_id,
        dataset_version=args.dataset_version,
        seed=args.seed,
        concurrency=args.concurrency,
        max_attempts=args.max_attempts,
        checkpoint_dir=args.checkpoint,
        budget=BudgetLimit(
            max_cases=max(len(cases), 1),
            max_model_calls=max(len(cases) * 32, 1),
            max_total_tokens=max(len(cases) * 100_000, 1),
        ),
        real_model=real_model,
        truth_class=(
            EvaluationTruthClass.OFFLINE_REAL_MODEL
            if real_model
            else EvaluationTruthClass.UNIT_FAKE
        ),
    )
    results = ExperimentRunner(executor).run(cases, config)
    report = build_report(
        results,
        dataset_version=config.dataset_version,
        truth_class=config.truth_class,
    )
    write_report_bundle(report, args.output)
    return 0 if len(results) == len(cases) and report.unclassified_exceptions == 0 else 1


def _load_cases(path: Path, *, limit: int | None) -> list[ExperimentCase]:
    rows = []
    for line in path.read_text("utf-8").splitlines():
        if not line.strip():
            continue
        payload: Any = json.loads(line)
        if not isinstance(payload, dict) or not isinstance(payload.get("case_id"), str):
            raise ValueError("each dataset row must be an object with case_id")
        resource_budget = payload.get("resource_budget", {})
        input_tokens = int(resource_budget.get("max_input_tokens", 0))
        output_tokens = int(resource_budget.get("max_output_tokens", 0))
        rows.append(
            ExperimentCase(
                case_id=payload["case_id"],
                payload=payload,
                reserved_model_calls=int(resource_budget.get("max_model_calls", 0)),
                reserved_total_tokens=input_tokens + output_tokens,
            )
        )
        if limit is not None and len(rows) >= limit:
            break
    if not rows:
        raise ValueError("dataset contains no cases")
    return rows


def _load_executor(reference: str) -> ExperimentExecutor:
    module_name, separator, attribute = reference.partition(":")
    if not separator or not module_name or not attribute:
        raise ValueError("executor factory must use module:callable syntax")
    factory = getattr(importlib.import_module(module_name), attribute)
    return cast(ExperimentExecutor, factory())
