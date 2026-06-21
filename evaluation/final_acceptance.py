"""Executable final acceptance for the ten product scenarios."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from evaluation.metadata import discover_metadata
from rag.citations import CitationAnswerService
from rag.retrieval import RetrievalHit


@dataclass(frozen=True)
class AcceptanceScenario:
    name: str
    pytest_nodes: tuple[str, ...]


@dataclass(frozen=True)
class ScenarioExecution:
    scenario: str
    passed: bool
    duration_seconds: float
    timed_out: bool
    output: str


@dataclass
class FinalAcceptanceReport:
    commit: str
    scenarios: list[ScenarioExecution]
    metrics: dict[str, float]
    gates: dict[str, bool]

    @property
    def passed(self) -> bool:
        return all(self.gates.values())

    def write_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "schema_version": "1.0",
            "commit": self.commit,
            "scenarios": [asdict(item) for item in self.scenarios],
            "metrics": self.metrics,
            "gates": self.gates,
            "passed": self.passed,
        }
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


ScenarioExecutor = Callable[[AcceptanceScenario], ScenarioExecution]


class FinalAcceptanceRunner:
    def __init__(
        self,
        scenarios: Sequence[AcceptanceScenario],
        *,
        executor: ScenarioExecutor,
    ) -> None:
        self._scenarios = list(scenarios)
        self._executor = executor

    def run(
        self,
        *,
        commit: str,
        citation_support_rate: float,
        deletion_unavailable: bool,
        adapter_free: bool,
    ) -> FinalAcceptanceReport:
        executions = [self._executor(scenario) for scenario in self._scenarios]
        total = max(1, len(executions))
        completion_rate = sum(item.passed for item in executions) / total
        dead_loop_rate = sum(item.timed_out for item in executions) / total
        metrics = {
            "completion_rate": completion_rate,
            "dead_loop_rate": dead_loop_rate,
            "citation_support_rate": citation_support_rate,
        }
        gates = {
            "completion_rate": completion_rate >= 0.80,
            "dead_loop_rate": dead_loop_rate == 0,
            "citation_support_rate": citation_support_rate >= 0.90,
            "deletion_unavailable": deletion_unavailable,
            "adapter_free": adapter_free,
        }
        return FinalAcceptanceReport(commit, executions, metrics, gates)


SCENARIOS = (
    AcceptanceScenario(
        "single_paper_qa",
        ("tests/test_citation_answers.py::test_citation_answer_evaluation_thresholds",),
    ),
    AcceptanceScenario(
        "requirement_clarification",
        (
            "tests/test_requirement_clarifier.py::"
            "test_answer_resumes_original_task_and_merges_constraints",
        ),
    ),
    AcceptanceScenario(
        "multi_paper_comparison",
        ("tests/test_multi_paper_comparison.py::test_comparison_evaluation_thresholds",),
    ),
    AcceptanceScenario(
        "historical_memory",
        (
            "tests/test_long_term_memory.py::"
            "test_cross_conversation_recall_file_link_and_preferences",
        ),
    ),
    AcceptanceScenario(
        "workspace_script_retrieval",
        ("tests/test_workspace_search.py::test_old_script_output_same_names_and_source_trace",),
    ),
    AcceptanceScenario(
        "section_drafting",
        ("tests/test_academic_drafting.py::test_drafting_evaluation_thresholds",),
    ),
    AcceptanceScenario(
        "section_rewriting",
        ("tests/test_academic_rewriting.py::test_rewriting_evaluation_thresholds",),
    ),
    AcceptanceScenario(
        "failure_replanning",
        ("tests/test_planner.py::test_replanner_allows_at_most_two_replans",),
    ),
    AcceptanceScenario(
        "cancel_and_recover",
        (
            "tests/test_worker.py::test_cancelled_task_is_not_executed",
            "tests/test_workspace_service.py::test_layout_manifest_promote_cleanup_and_recovery",
        ),
    ),
    AcceptanceScenario(
        "delete_and_forget",
        ("tests/test_long_term_memory.py::test_forget_removes_summary_and_historical_file",),
    ),
)


def _pytest_executor(root: Path, timeout_seconds: int) -> ScenarioExecutor:
    def execute(scenario: AcceptanceScenario) -> ScenarioExecution:
        started = time.monotonic()
        try:
            completed = subprocess.run(
                [sys.executable, "-m", "pytest", *scenario.pytest_nodes, "-q"],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
            output = (completed.stdout + completed.stderr)[-4000:]
            return ScenarioExecution(
                scenario.name,
                completed.returncode == 0,
                round(time.monotonic() - started, 3),
                False,
                output,
            )
        except subprocess.TimeoutExpired as exc:
            return ScenarioExecution(
                scenario.name,
                False,
                round(time.monotonic() - started, 3),
                True,
                str(exc),
            )

    return execute


def measure_citation_support_rate() -> float:
    service = CitationAnswerService()
    supported = 0
    total = 80
    for index in range(total):
        result = service.answer(
            "What accuracy did the method achieve?",
            [
                RetrievalHit(
                    chunk_id=f"chunk-{index}",
                    workspace_id="ws",
                    file_id="paper",
                    text=f"The method achieved accuracy {80 + index % 20}% on the benchmark.",
                    section_path=("Results",),
                    page_start=1,
                    page_end=1,
                    bbox=(0.0, 0.0, 1.0, 1.0),
                    source_block_ids=(f"block-{index}",),
                    score=1.0,
                )
            ],
        )
        supported += int(
            result.answerable
            and all(
                service._checker.supported(
                    claim.text,
                    result.citations,
                    claim.citation_ids,
                )
                for claim in result.claims
            )
        )
    return supported / total


def _run_gate(root: Path, node: str, timeout_seconds: int) -> bool:
    try:
        return (
            subprocess.run(
                [sys.executable, "-m", "pytest", node, "-q"],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            ).returncode
            == 0
        )
    except subprocess.TimeoutExpired:
        return False


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run final PaperAgent acceptance")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("evaluation/reports/final_acceptance.json"),
    )
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    metadata = discover_metadata(root)
    runner = FinalAcceptanceRunner(
        SCENARIOS,
        executor=_pytest_executor(root, args.timeout),
    )
    deletion_unavailable = _run_gate(
        root,
        "tests/test_workspace_search.py::test_deletion_invalidates_search_and_location_rate",
        args.timeout,
    )
    adapter_free = _run_gate(
        root,
        "tests/test_model_runtime.py::test_registry_supports_base_model_without_adapters",
        args.timeout,
    )
    report = runner.run(
        commit=metadata.commit,
        citation_support_rate=measure_citation_support_rate(),
        deletion_unavailable=deletion_unavailable,
        adapter_free=adapter_free,
    )
    output = args.output if args.output.is_absolute() else root / args.output
    report.write_json(output)
    print(f"final acceptance report: {output}")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
