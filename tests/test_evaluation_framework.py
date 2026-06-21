import json
from pathlib import Path

from evaluation.cli import main
from evaluation.runner import EvaluationRunner
from evaluation.schema import EvaluationMetadata, EvaluationResult, EvaluationSuite


def _passing(suite: EvaluationSuite) -> EvaluationResult:
    return EvaluationResult(
        suite=suite,
        passed=True,
        metrics={"success_rate": 1.0},
        failures=[],
    )


def test_runner_emits_all_seven_report_levels_with_reproducibility_metadata(
    tmp_path: Path,
) -> None:
    metadata = EvaluationMetadata(
        commit="abc123",
        config={"environment": "test"},
        profiles={"development": "base-1.7b-v1"},
        skills={"paper_reader": "1.0.0"},
        datasets={"security": "security-v1"},
        prompts={"paper_reader": "sha256:prompt"},
    )
    runner = EvaluationRunner(
        evaluators={suite: (lambda suite=suite: _passing(suite)) for suite in EvaluationSuite}
    )

    report = runner.run(list(EvaluationSuite), metadata=metadata)
    output = tmp_path / "report.json"
    report.write_json(output)

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert {item["suite"] for item in payload["results"]} == {
        suite.value for suite in EvaluationSuite
    }
    assert payload["metadata"]["commit"] == "abc123"
    assert payload["metadata"]["config"]["environment"] == "test"
    assert payload["metadata"]["profiles"]["development"] == "base-1.7b-v1"
    assert payload["metadata"]["skills"]["paper_reader"] == "1.0.0"
    assert payload["metadata"]["datasets"]["security"] == "security-v1"
    assert payload["metadata"]["prompts"]["paper_reader"] == "sha256:prompt"
    assert payload["passed"] is True


def test_cli_runs_selected_evaluations_with_one_command(tmp_path: Path) -> None:
    output = tmp_path / "selected.json"

    exit_code = main(
        [
            "--suite",
            "contract",
            "--suite",
            "security",
            "--output",
            str(output),
        ]
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert [item["suite"] for item in payload["results"]] == ["contract", "security"]
    assert payload["metadata"]["commit"]
    assert payload["metadata"]["config"]["registry"] == "models/registry.yaml"
    assert payload["metadata"]["profiles"]
    assert payload["metadata"]["skills"]
    assert payload["metadata"]["datasets"]
