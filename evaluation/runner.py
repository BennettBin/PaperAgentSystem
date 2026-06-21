"""Composable runner for the seven required evaluation levels."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping

from evaluation.schema import (
    EvaluationMetadata,
    EvaluationReport,
    EvaluationResult,
    EvaluationSuite,
)

Evaluator = Callable[[], EvaluationResult]


class EvaluationRunner:
    def __init__(self, evaluators: Mapping[EvaluationSuite, Evaluator]) -> None:
        self._evaluators = dict(evaluators)

    def run(
        self,
        suites: Iterable[EvaluationSuite],
        *,
        metadata: EvaluationMetadata,
    ) -> EvaluationReport:
        results: list[EvaluationResult] = []
        for suite in suites:
            evaluator = self._evaluators.get(suite)
            if evaluator is None:
                results.append(
                    EvaluationResult(
                        suite=suite,
                        passed=False,
                        failures=[f"No evaluator registered for {suite.value}"],
                    )
                )
                continue
            result = evaluator()
            if result.suite is not suite:
                raise ValueError(
                    f"Evaluator for {suite.value} returned result for {result.suite.value}"
                )
            results.append(result)
        return EvaluationReport(metadata=metadata, results=results)
