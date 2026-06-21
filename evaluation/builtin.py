"""Deterministic repository checks used by the default evaluation command."""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from pathlib import Path

from evaluation.schema import EvaluationResult, EvaluationSuite


def _repository_check(
    root: Path,
    suite: EvaluationSuite,
    required_paths: tuple[str, ...],
) -> EvaluationResult:
    missing = [path for path in required_paths if not (root / path).exists()]
    return EvaluationResult(
        suite=suite,
        passed=not missing,
        metrics={
            "required_artifacts": len(required_paths),
            "present_artifacts": len(required_paths) - len(missing),
        },
        failures=[f"Missing required artifact: {path}" for path in missing],
    )


def built_in_evaluators(root: Path) -> dict[EvaluationSuite, Callable[[], EvaluationResult]]:
    requirements = {
        EvaluationSuite.CONTRACT: (
            "core/ports",
            "tests/test_fake_adapters.py",
        ),
        EvaluationSuite.COMPONENT: (
            "agent_runtime",
            "tests/test_agent_runtime.py",
        ),
        EvaluationSuite.TRAJECTORY: (
            "agent_runtime/state_machine.py",
            "observability/tracing.py",
        ),
        EvaluationSuite.DOMAIN: (
            "academic_tasks",
            "tests/test_academic_drafting.py",
        ),
        EvaluationSuite.E2E: (
            "apps/api/main.py",
            "tests/test_api_app.py",
        ),
        EvaluationSuite.SECURITY: (
            "security/guard.py",
            "tests/test_security_hardening.py",
        ),
        EvaluationSuite.PERFORMANCE: (
            "tests/test_hybrid_retrieval.py",
            "tests/test_context_builder.py",
        ),
    }
    return {
        suite: partial(_repository_check, root, suite, paths)
        for suite, paths in requirements.items()
    }
