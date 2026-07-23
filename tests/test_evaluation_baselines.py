import json
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from evaluation.baselines import (
    BaselineKind,
    EvaluationTruthClass,
    load_baseline,
    load_baselines,
)
from evaluation.cli import main

ROOT = Path(__file__).resolve().parents[1]


def test_all_four_frozen_baselines_have_unique_ids_and_truth_gates() -> None:
    baselines = load_baselines(ROOT / "evaluation" / "baselines")

    assert {baseline.kind for baseline in baselines} == set(BaselineKind)
    assert len({baseline.baseline_id for baseline in baselines}) == 4
    assert all(baseline.frozen for baseline in baselines)
    assert all(baseline.effect_metrics_require_real_model for baseline in baselines)
    assert all(
        EvaluationTruthClass.OFFLINE_REAL_MODEL in baseline.allowed_truth_classes
        for baseline in baselines
    )
    assert all(
        EvaluationTruthClass.UNIT_FAKE not in baseline.effect_metric_truth_classes
        for baseline in baselines
    )
    assert len({baseline.config_hash for baseline in baselines}) == 4


def test_invalid_baseline_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "invalid.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "1.0",
                "baseline_id": "invalid",
                "label": "Invalid",
                "kind": "vanilla_rag",
                "frozen": False,
                "description": "Missing required execution and truth gates.",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        load_baseline(path)


def test_each_baseline_runs_through_same_cli_runner_and_is_recorded(
    tmp_path: Path,
) -> None:
    baselines = load_baselines(ROOT / "evaluation" / "baselines")
    for baseline in baselines:
        first = tmp_path / f"{baseline.baseline_id}-first.json"
        second = tmp_path / f"{baseline.baseline_id}-second.json"
        assert main(
            [
                "--suite",
                "contract",
                "--baseline",
                baseline.baseline_id,
                "--output",
                str(first),
            ]
        ) == 0
        assert main(
            [
                "--suite",
                "contract",
                "--baseline",
                baseline.baseline_id,
                "--output",
                str(second),
            ]
        ) == 0
        first_payload = json.loads(first.read_text(encoding="utf-8"))
        second_payload = json.loads(second.read_text(encoding="utf-8"))
        assert first_payload["results"] == second_payload["results"]
        assert first_payload["metadata"]["config"]["baseline_id"] == baseline.baseline_id
        assert isinstance(first_payload["metadata"]["config"]["git_dirty"], bool)
        assert isinstance(
            first_payload["metadata"]["config"]["git_dirty_entries"], int
        )
        assert (
            first_payload["metadata"]["config"]["baseline_config_hash"]
            == baseline.config_hash
        )
        assert (
            second_payload["metadata"]["config"]["baseline_config_hash"]
            == baseline.config_hash
        )
