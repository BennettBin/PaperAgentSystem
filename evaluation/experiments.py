"""Resumable experiment execution, trace replay, and deterministic reporting.

This module is intentionally evaluation-only.  It consumes an executor through a
small protocol and does not alter the production Agent Runtime state machine.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from evaluation.baselines import EvaluationTruthClass


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ErrorCategory(StrEnum):
    ROUTING = "routing"
    PLANNING = "planning"
    RETRIEVAL = "retrieval"
    TOOL_PARAMETERS = "tool_parameters"
    GENERATION = "generation"
    VERIFICATION = "verification"
    SYSTEM = "system"
    DATA = "data"


_ERROR_PREFIXES: tuple[tuple[ErrorCategory, tuple[str, ...]], ...] = (
    (ErrorCategory.ROUTING, ("route", "routing", "skill_")),
    (ErrorCategory.PLANNING, ("plan", "invalid_plan", "dependency", "budget_plan")),
    (ErrorCategory.RETRIEVAL, ("rag", "retriev", "evidence_not_found")),
    (ErrorCategory.TOOL_PARAMETERS, ("tool_invalid", "tool_argument", "schema_tool")),
    (ErrorCategory.GENERATION, ("generation", "unsupported_claim", "hallucination")),
    (ErrorCategory.VERIFICATION, ("verif", "citation_", "invariant_")),
    (ErrorCategory.DATA, ("data", "invalid_gold", "dataset", "source_")),
    (ErrorCategory.SYSTEM, ("system", "timeout", "exception", "worker", "network")),
)


def classify_error(code: str) -> ErrorCategory:
    """Map every error to the closed L04 taxonomy; unknowns fail safe as system."""

    normalized = code.strip().casefold()
    for category, prefixes in _ERROR_PREFIXES:
        if normalized.startswith(prefixes):
            return category
    return ErrorCategory.SYSTEM


class BudgetLimit(_StrictModel):
    max_cases: int = Field(gt=0)
    max_model_calls: int = Field(ge=0)
    max_total_tokens: int = Field(ge=0)


class ExperimentRunConfig(_StrictModel):
    run_id: str = Field(min_length=1)
    system_id: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    seed: int = 0
    concurrency: int = Field(default=1, ge=1, le=64)
    max_attempts: int = Field(default=1, ge=1, le=10)
    checkpoint_dir: Path
    budget: BudgetLimit
    real_model: bool = False
    truth_class: EvaluationTruthClass = EvaluationTruthClass.UNIT_FAKE
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_real_model_truth(self) -> ExperimentRunConfig:
        if self.real_model and self.truth_class is not EvaluationTruthClass.OFFLINE_REAL_MODEL:
            raise ValueError("real-model runs require offline_real_model truth class")
        if not self.real_model and self.truth_class is EvaluationTruthClass.OFFLINE_REAL_MODEL:
            raise ValueError("offline_real_model truth class requires a real-model run")
        return self


class ExperimentCase(_StrictModel):
    case_id: str = Field(min_length=1)
    payload: dict[str, Any]
    reserved_model_calls: int = Field(default=0, ge=0)
    reserved_total_tokens: int = Field(default=0, ge=0)


class ModelCall(_StrictModel):
    model: str = Field(min_length=1)
    profile: str = Field(min_length=1)
    version: str = Field(min_length=1)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    latency_ms: int = Field(ge=0)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class TraceEvent(_StrictModel):
    sequence: int = Field(ge=1)
    kind: str = Field(min_length=1)
    data: dict[str, Any] = Field(default_factory=dict)


class ExperimentResult(_StrictModel):
    case_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    system_id: str = Field(min_length=1)
    passed: bool
    error_code: str | None = None
    error_category: ErrorCategory | None = None
    model_calls: list[ModelCall] = Field(default_factory=list)
    trace: list[TraceEvent] = Field(default_factory=list)
    output: dict[str, Any] = Field(default_factory=dict)
    attempts: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def classify_failure(self) -> ExperimentResult:
        if not self.passed and self.error_category is None:
            self.error_category = classify_error(self.error_code or "unclassified_exception")
        return self

    @property
    def total_tokens(self) -> int:
        return sum(call.total_tokens for call in self.model_calls)


class ExperimentExecutor(Protocol):
    def execute(
        self, case: ExperimentCase, *, seed: int, attempt: int
    ) -> ExperimentResult: ...


class ExperimentRunner:
    """Concurrent runner with deterministic seeds and atomic per-case checkpoints."""

    def __init__(self, executor: ExperimentExecutor) -> None:
        self._executor = executor

    @staticmethod
    def case_seed(seed: int, case_id: str) -> int:
        digest = hashlib.sha256(f"{seed}:{case_id}".encode()).digest()
        return int.from_bytes(digest[:8], "big")

    def run(
        self,
        cases: Iterable[ExperimentCase],
        config: ExperimentRunConfig,
    ) -> list[ExperimentResult]:
        ordered_cases = list(cases)
        if len({case.case_id for case in ordered_cases}) != len(ordered_cases):
            raise ValueError("duplicate case_id in experiment input")
        run_dir = config.checkpoint_dir / _safe_name(config.run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        self._write_or_validate_manifest(run_dir, config)

        completed = {
            case.case_id: result
            for case in ordered_cases
            if (result := self._load_result(run_dir, case.case_id)) is not None
        }
        used_calls = sum(len(item.model_calls) for item in completed.values())
        used_tokens = sum(item.total_tokens for item in completed.values())
        remaining_case_slots = max(config.budget.max_cases - len(completed), 0)
        pending = [case for case in ordered_cases if case.case_id not in completed]
        if used_calls >= config.budget.max_model_calls or used_tokens >= config.budget.max_total_tokens:
            pending = []
        admitted: list[ExperimentCase] = []
        reserved_calls = used_calls
        reserved_tokens = used_tokens
        for case in pending[:remaining_case_slots]:
            if reserved_calls + case.reserved_model_calls > config.budget.max_model_calls:
                continue
            if reserved_tokens + case.reserved_total_tokens > config.budget.max_total_tokens:
                continue
            admitted.append(case)
            reserved_calls += case.reserved_model_calls
            reserved_tokens += case.reserved_total_tokens

        # Submit at most the currently allowed case count. Results are checkpointed
        # atomically as each future completes, so interruption cannot overwrite a
        # prior completed case or count it twice on resume.
        with ThreadPoolExecutor(max_workers=config.concurrency) as pool:
            futures = {
                pool.submit(self._execute_with_retry, case, config): case
                for case in admitted
            }
            for future in as_completed(futures):
                result = future.result()
                completed[result.case_id] = result
                self._write_result(run_dir, result)

        return [completed[case.case_id] for case in ordered_cases if case.case_id in completed]

    def _execute_with_retry(
        self, case: ExperimentCase, config: ExperimentRunConfig
    ) -> ExperimentResult:
        seed = self.case_seed(config.seed, case.case_id)
        for attempt in range(1, config.max_attempts + 1):
            try:
                result = self._executor.execute(case, seed=seed, attempt=attempt)
                if result.case_id != case.case_id:
                    raise ValueError("executor returned a different case_id")
                return result.model_copy(
                    update={"system_id": config.system_id, "attempts": attempt}
                )
            except Exception as exc:
                if attempt == config.max_attempts:
                    code = "timeout" if isinstance(exc, TimeoutError) else "system_exception"
                    return ExperimentResult(
                        case_id=case.case_id,
                        task_id=f"failed-{case.case_id}",
                        system_id=config.system_id,
                        passed=False,
                        error_code=code,
                        error_category=classify_error(code),
                        attempts=attempt,
                        trace=[
                            TraceEvent(
                                sequence=1,
                                kind="observation",
                                data={"error_type": type(exc).__name__},
                            )
                        ],
                    )
        raise AssertionError("unreachable")

    @staticmethod
    def _write_or_validate_manifest(run_dir: Path, config: ExperimentRunConfig) -> None:
        path = run_dir / "run.json"
        payload = config.model_dump(mode="json", exclude={"checkpoint_dir"})
        if path.exists():
            if json.loads(path.read_text("utf-8")) != payload:
                raise ValueError("resume config differs from the checkpoint manifest")
            return
        _atomic_json(path, payload)

    @staticmethod
    def _result_path(run_dir: Path, case_id: str) -> Path:
        return run_dir / "results" / f"{_safe_name(case_id)}.json"

    def _load_result(self, run_dir: Path, case_id: str) -> ExperimentResult | None:
        path = self._result_path(run_dir, case_id)
        if not path.exists():
            return None
        result = ExperimentResult.model_validate_json(path.read_text("utf-8"))
        if result.case_id != case_id:
            raise ValueError("checkpoint case_id does not match requested case")
        return result

    def _write_result(self, run_dir: Path, result: ExperimentResult) -> None:
        _atomic_json(
            self._result_path(run_dir, result.case_id), result.model_dump(mode="json")
        )


class ReplayView(_StrictModel):
    case_id: str
    task_id: str
    timeline: list[TraceEvent]
    plan_versions: list[int | str]
    model_calls: list[ModelCall]
    tool_results: list[dict[str, Any]]
    budget_changes: list[dict[str, Any]]


class TraceReplay:
    def __init__(self, views: Iterable[ReplayView]) -> None:
        self._by_case = {view.case_id: view for view in views}
        self._by_task = {view.task_id: view for view in views}

    @classmethod
    def from_results(cls, results: Iterable[ExperimentResult]) -> TraceReplay:
        views = []
        for result in results:
            timeline = sorted(result.trace, key=lambda event: event.sequence)
            views.append(
                ReplayView(
                    case_id=result.case_id,
                    task_id=result.task_id,
                    timeline=timeline,
                    plan_versions=[
                        event.data["version"]
                        for event in timeline
                        if event.kind == "plan" and "version" in event.data
                    ],
                    model_calls=result.model_calls,
                    tool_results=[
                        event.data for event in timeline if event.kind == "tool_result"
                    ],
                    budget_changes=[
                        event.data for event in timeline if event.kind == "budget"
                    ],
                )
            )
        return cls(views)

    def by_case_id(self, case_id: str) -> ReplayView:
        return self._by_case[case_id]

    def by_task_id(self, task_id: str) -> ReplayView:
        return self._by_task[task_id]


class SystemSummary(_StrictModel):
    system_id: str
    case_count: int
    passed: int
    pass_rate: float
    model_calls: int
    total_tokens: int
    system_error_rate: float
    errors: dict[str, int]


class ExperimentReport(_StrictModel):
    schema_version: str = "1.0"
    dataset_version: str
    truth_class: EvaluationTruthClass
    case_count: int
    unclassified_exceptions: int
    comparison: list[SystemSummary]


_SYSTEM_ORDER = {"b0": 0, "b1": 1, "b2": 2, "b3": 3, "candidate": 4}


def build_report(
    results: Iterable[ExperimentResult | dict[str, Any]], *, dataset_version: str,
    truth_class: EvaluationTruthClass = EvaluationTruthClass.UNIT_FAKE,
) -> ExperimentReport:
    validated: list[ExperimentResult] = []
    for raw in results:
        try:
            payload = raw.model_dump(mode="python") if isinstance(raw, BaseModel) else raw
            result = ExperimentResult.model_validate(payload)
        except Exception as exc:
            raise ValueError("incomplete model call metadata or invalid result") from exc
        validated.append(result)
    grouped: dict[str, list[ExperimentResult]] = {}
    for result in validated:
        grouped.setdefault(result.system_id, []).append(result)
    comparison = []
    for system_id, items in grouped.items():
        errors = Counter(
            item.error_category.value for item in items if item.error_category is not None
        )
        system_errors = errors[ErrorCategory.SYSTEM.value]
        comparison.append(
            SystemSummary(
                system_id=system_id,
                case_count=len(items),
                passed=sum(item.passed for item in items),
                pass_rate=sum(item.passed for item in items) / len(items),
                model_calls=sum(len(item.model_calls) for item in items),
                total_tokens=sum(item.total_tokens for item in items),
                system_error_rate=system_errors / len(items),
                errors=dict(sorted(errors.items())),
            )
        )
    comparison.sort(key=lambda item: (_SYSTEM_ORDER.get(item.system_id, 99), item.system_id))
    unclassified = sum(
        not item.passed and item.error_category is None for item in validated
    )
    return ExperimentReport(
        dataset_version=dataset_version,
        truth_class=truth_class,
        case_count=len(validated),
        unclassified_exceptions=unclassified,
        comparison=comparison,
    )


def write_report_bundle(report: ExperimentReport, directory: Path) -> dict[str, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / "report.json"
    markdown_path = directory / "report.md"
    dashboard_path = directory / "dashboard.json"
    _atomic_json(json_path, report.model_dump(mode="json"))
    lines = [
        "# Experiment report",
        "",
        f"Dataset: `{report.dataset_version}`; cases: {report.case_count}.",
        f"Truth class: `{report.truth_class.value}`.",
        "",
        "| System | Cases | Passed | Pass rate | Model calls | Tokens | System errors |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in report.comparison:
        lines.append(
            f"| {row.system_id} | {row.case_count} | {row.passed} | "
            f"{row.pass_rate:.4f} | {row.model_calls} | {row.total_tokens} | "
            f"{row.system_error_rate:.4f} |"
        )
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _atomic_json(
        dashboard_path,
        {
            "schema_version": report.schema_version,
            "dataset_version": report.dataset_version,
            "truth_class": report.truth_class.value,
            "case_count": report.case_count,
            "systems": [item.model_dump(mode="json") for item in report.comparison],
        },
    )
    return {"json": json_path, "markdown": markdown_path, "dashboard": dashboard_path}


def _safe_name(value: str) -> str:
    # A short content-derived name keeps Windows checkpoint paths below MAX_PATH;
    # the full case_id is verified inside every checkpoint before it is trusted.
    return hashlib.sha256(value.encode()).hexdigest()[:16]


def _atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
