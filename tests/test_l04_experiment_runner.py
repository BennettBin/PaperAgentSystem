from __future__ import annotations

import json
from pathlib import Path

import pytest

from evaluation.experiment_cli import real_main, smoke_main
from evaluation.experiments import (
    BudgetLimit,
    ErrorCategory,
    ExperimentCase,
    ExperimentResult,
    ExperimentRunConfig,
    ExperimentRunner,
    ModelCall,
    TraceEvent,
    TraceReplay,
    build_report,
    classify_error,
    write_report_bundle,
)


class RecordingExecutor:
    def __init__(self, *, fail_once: set[str] | None = None) -> None:
        self.calls: list[tuple[str, int, int]] = []
        self.fail_once = fail_once or set()

    def execute(self, case: ExperimentCase, *, seed: int, attempt: int) -> ExperimentResult:
        self.calls.append((case.case_id, seed, attempt))
        if case.case_id in self.fail_once and attempt == 1:
            raise TimeoutError("temporary timeout")
        return ExperimentResult(
            case_id=case.case_id,
            task_id=f"task-{case.case_id}",
            system_id="candidate",
            passed=True,
            model_calls=[
                ModelCall(
                    model="fake-model",
                    profile="ci-smoke",
                    version="1",
                    input_tokens=2,
                    output_tokens=1,
                    latency_ms=3,
                )
            ],
            trace=[
                TraceEvent(sequence=1, kind="decision", data={"state": "planned"}),
                TraceEvent(sequence=2, kind="plan", data={"version": 1}),
                TraceEvent(sequence=3, kind="action", data={"tool": "search"}),
                TraceEvent(sequence=4, kind="observation", data={"ok": True}),
                TraceEvent(sequence=5, kind="budget", data={"tokens_delta": 3}),
            ],
        )


def _config(tmp_path: Path, **updates: object) -> ExperimentRunConfig:
    values: dict[str, object] = {
        "run_id": "run-1",
        "system_id": "candidate",
        "dataset_version": "l02-v1",
        "seed": 17,
        "concurrency": 2,
        "max_attempts": 2,
        "checkpoint_dir": tmp_path / "checkpoint",
        "budget": BudgetLimit(max_cases=10, max_model_calls=10, max_total_tokens=100),
    }
    values.update(updates)
    return ExperimentRunConfig(**values)


def test_runner_retries_deterministically_and_resume_is_idempotent(tmp_path: Path) -> None:
    cases = [ExperimentCase(case_id=f"c-{index}", payload={}) for index in range(3)]
    executor = RecordingExecutor(fail_once={"c-1"})
    runner = ExperimentRunner(executor)

    first = runner.run(cases, _config(tmp_path))
    assert len(first) == 3
    assert [call[0] for call in executor.calls].count("c-1") == 2
    assert {call[1] for call in executor.calls if call[0] == "c-1"} == {
        ExperimentRunner.case_seed(17, "c-1")
    }

    billed = sum(result.total_tokens for result in first)
    calls_before_resume = list(executor.calls)
    second = runner.run(cases, _config(tmp_path))
    assert executor.calls == calls_before_resume
    assert sum(result.total_tokens for result in second) == billed
    assert [result.model_dump() for result in second] == [
        result.model_dump() for result in first
    ]


def test_budget_stops_new_cases_without_corrupting_completed_results(tmp_path: Path) -> None:
    cases = [ExperimentCase(case_id=f"c-{index}", payload={}) for index in range(3)]
    executor = RecordingExecutor()
    config = _config(
        tmp_path,
        concurrency=1,
        budget=BudgetLimit(max_cases=2, max_model_calls=10, max_total_tokens=100),
    )
    results = ExperimentRunner(executor).run(cases, config)
    assert len(results) == 2
    assert {result.case_id for result in results} == {"c-0", "c-1"}


def test_budget_admission_reserves_model_calls_and_tokens(tmp_path: Path) -> None:
    cases = [
        ExperimentCase(
            case_id=f"c-{index}",
            payload={},
            reserved_model_calls=2,
            reserved_total_tokens=30,
        )
        for index in range(3)
    ]
    executor = RecordingExecutor()
    results = ExperimentRunner(executor).run(
        cases,
        _config(
            tmp_path,
            budget=BudgetLimit(max_cases=3, max_model_calls=4, max_total_tokens=60),
        ),
    )
    assert len(results) == 2
    assert len(executor.calls) == 2


def test_trace_replay_supports_case_and_task_lookup(tmp_path: Path) -> None:
    result = ExperimentRunner(RecordingExecutor()).run(
        [ExperimentCase(case_id="c-1", payload={})], _config(tmp_path)
    )[0]
    replay = TraceReplay.from_results([result])

    by_case = replay.by_case_id("c-1")
    by_task = replay.by_task_id("task-c-1")
    assert by_case == by_task
    assert by_case.plan_versions == [1]
    assert [event.kind for event in by_case.timeline] == [
        "decision",
        "plan",
        "action",
        "observation",
        "budget",
    ]
    assert by_case.budget_changes == [{"tokens_delta": 3}]


def test_failed_case_remains_replayable(tmp_path: Path) -> None:
    result = ExperimentRunner(RecordingExecutor(fail_once={"c-1"})).run(
        [ExperimentCase(case_id="c-1", payload={})],
        _config(tmp_path, max_attempts=1),
    )[0]
    replay = TraceReplay.from_results([result])
    assert result.error_category is ErrorCategory.SYSTEM
    assert replay.by_case_id("c-1") == replay.by_task_id("failed-c-1")


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("skill_route_miss", ErrorCategory.ROUTING),
        ("invalid_plan", ErrorCategory.PLANNING),
        ("rag_empty", ErrorCategory.RETRIEVAL),
        ("tool_invalid_arguments", ErrorCategory.TOOL_PARAMETERS),
        ("unsupported_claim", ErrorCategory.GENERATION),
        ("citation_verification_failed", ErrorCategory.VERIFICATION),
        ("timeout", ErrorCategory.SYSTEM),
        ("invalid_gold", ErrorCategory.DATA),
    ],
)
def test_error_taxonomy_is_closed(code: str, expected: ErrorCategory) -> None:
    assert classify_error(code) is expected
    assert classify_error("never-seen") is ErrorCategory.SYSTEM


def test_report_is_deterministic_and_rejects_incomplete_model_metadata(tmp_path: Path) -> None:
    result = ExperimentRunner(RecordingExecutor()).run(
        [ExperimentCase(case_id="c-1", payload={})], _config(tmp_path)
    )[0]
    report_a = build_report([result], dataset_version="l02-v1")
    report_b = build_report([result], dataset_version="l02-v1")
    assert report_a.model_dump(mode="json") == report_b.model_dump(mode="json")

    invalid = result.model_dump(mode="python")
    invalid["model_calls"] = [{"model": "x", "profile": "", "version": "1"}]
    with pytest.raises(ValueError, match="model call metadata"):
        build_report([invalid], dataset_version="l02-v1")


def test_report_bundle_outputs_json_markdown_dashboard_and_comparison(tmp_path: Path) -> None:
    results = []
    for system in ("b0", "b1", "b2", "b3", "candidate"):
        result = ExperimentRunner(RecordingExecutor()).run(
            [ExperimentCase(case_id=f"{system}-1", payload={})],
            _config(tmp_path / system, run_id=f"run-{system}", system_id=system),
        )[0].model_copy(update={"system_id": system})
        results.append(result)
    report = build_report(results, dataset_version="l02-v1")
    paths = write_report_bundle(report, tmp_path / "reports")

    assert set(paths) == {"json", "markdown", "dashboard"}
    assert all(path.exists() for path in paths.values())
    assert [row.system_id for row in report.comparison] == [
        "b0",
        "b1",
        "b2",
        "b3",
        "candidate",
    ]
    dashboard = json.loads(paths["dashboard"].read_text("utf-8"))
    assert dashboard["schema_version"] == "1.0"
    assert len(dashboard["systems"]) == 5


def test_smoke_cli_runs_jsonl_but_real_cli_requires_explicit_gate(tmp_path: Path) -> None:
    dataset = tmp_path / "cases.jsonl"
    dataset.write_text('{"case_id":"c-1"}\n', encoding="utf-8")
    common = [
        "--dataset", str(dataset),
        "--output", str(tmp_path / "out"),
        "--checkpoint", str(tmp_path / "checkpoint"),
        "--run-id", "smoke-1",
    ]
    assert smoke_main(common) == 0
    dashboard = json.loads((tmp_path / "out" / "dashboard.json").read_text("utf-8"))
    assert dashboard["truth_class"] == "unit_fake"
    with pytest.raises(SystemExit):
        real_main([*common, "--executor-factory", "example:factory"])
