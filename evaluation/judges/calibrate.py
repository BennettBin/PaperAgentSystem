"""Generate the fixed 50-case L03 Judge calibration report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evaluation.datasets.audit import load_cases
from evaluation.datasets.schema import JudgeVerdict
from evaluation.judges.system import JudgeInput, JudgeSystem, ProgrammaticJudge


def build_calibration_report(cases_path: Path) -> dict[str, object]:
    cases = [
        case
        for case in load_cases(cases_path)
        if case.requires_evidence and case.reference_answer is not None
    ][:50]
    if len(cases) != 50:
        raise ValueError("Judge calibration requires 50 human-reference cases")
    system = JudgeSystem(programmatic=ProgrammaticJudge())
    results: list[dict[str, object]] = []
    agreements = 0
    consistent = 0
    for index, case in enumerate(cases):
        reference = case.reference_answer
        if reference is None:
            raise ValueError(f"calibration case {case.case_id} lacks a reference answer")
        positive = index < 25
        judge_input = JudgeInput(
            case=case,
            candidate_answer=(
                reference.answer
                if positive
                else "Insufficient evidence to provide the requested answer."
            ),
            candidate_evidence_ids=(
                [item.evidence_id for item in case.required_evidence] if positive else []
            ),
        )
        expected = JudgeVerdict.PASS if positive else JudgeVerdict.FAIL
        repeated = system.judge_repeated(judge_input, repetitions=3)
        agreements += repeated.final_result.verdict is expected
        consistent += repeated.consistency >= 0.95
        results.append(
            {
                "case_id": case.case_id,
                "expected_verdict": expected.value,
                "actual_verdict": repeated.final_result.verdict.value,
                "three_run_consistency": repeated.consistency,
                "judge_type": repeated.final_result.judge_type.value,
                "judge_version": repeated.final_result.judge_version,
                "reason_summary": repeated.final_result.reason_summary,
                "evidence_ids": repeated.final_result.evidence_ids,
                "calibration_variant": "human_reference_exact" if positive else "controlled_missing_evidence_negative",
            }
        )
    return {
        "schema_version": "1.0",
        "generated_at": "2026-07-21T00:00:00Z",
        "dataset_version": "paperagent-eval-v1",
        "truth_class": "integration_real",
        "gold_truth_class": "human_review",
        "gold_provenance": "L02 QASPER human reference answers; negative candidates are controlled perturbations, not human answers",
        "case_count": len(cases),
        "human_reference_gold_count": len(cases),
        "controlled_negative_count": 25,
        "agreement_rate": agreements / len(cases),
        "three_run_consistency_rate": consistent / len(cases),
        "results": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build L03 Judge calibration report")
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = build_calibration_report(args.cases)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
