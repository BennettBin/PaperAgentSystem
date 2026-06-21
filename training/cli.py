"""Standalone training-data command line interface."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from training.bundle import load_exported_bundle
from training.dataset import validate_dataset
from training.preflight import PreflightRequest, run_preflight


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PaperAgent offline training tools")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--bundle", type=Path, required=True)
    validate.add_argument("--dataset", type=Path, required=True)
    preflight = subparsers.add_parser("preflight")
    preflight.add_argument("--task", required=True)
    preflight.add_argument("--dataset", type=Path, required=True)
    preflight.add_argument("--base-model", type=Path, required=True)
    preflight.add_argument(
        "--catalog",
        type=Path,
        default=Path("training/configs/profiles.yaml"),
    )
    preflight.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    if args.command == "preflight":
        report = run_preflight(
            PreflightRequest(
                task=args.task,
                dataset=args.dataset,
                base_model=args.base_model,
                catalog=args.catalog,
            )
        )
        if args.output:
            report.write_json(args.output)
        print(report.model_dump_json())
        return 0 if report.ready else 2

    manifest, payload = load_exported_bundle(args.bundle)
    result = validate_dataset(args.dataset)
    print(
        json.dumps(
            {
                "bundle_version": manifest.bundle_version,
                "sample_count": result.sample_count,
                "split_counts": result.split_counts,
                "tool_count": len(payload["tool_definitions"]["tools"]),
            },
            ensure_ascii=False,
        )
    )
    return 0
