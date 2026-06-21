import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from training.contracts import (
    DatasetManifest,
    DatasetSplit,
    PrivacyLabel,
    TrainingSample,
)
from training.dataset import DatasetValidationError, validate_dataset

ROOT = Path(__file__).resolve().parents[1]


def sample(**overrides: object) -> TrainingSample:
    values: dict[str, object] = {
        "sample_id": "router-001",
        "task_type": "router",
        "source": "synthetic",
        "base_model_family": "qwen3-1.7b",
        "input": {"request": "Compare two papers"},
        "tools": [],
        "context": {},
        "sft_target": {"intent": "paper_comparison"},
        "dataset_split": DatasetSplit.TRAIN,
        "paper_ids": ["synthetic-paper-1"],
        "conversation_ids": ["synthetic-conversation-1"],
        "license": "CC0-1.0",
        "privacy": PrivacyLabel.SYNTHETIC,
        "human_review_status": "approved",
    }
    values.update(overrides)
    return TrainingSample.model_validate(values)


def test_training_sample_requires_exactly_one_learning_target() -> None:
    with pytest.raises(ValidationError):
        sample(sft_target=None)
    with pytest.raises(ValidationError):
        sample(chosen={"ok": True}, rejected={"ok": False})

    preference = sample(
        sft_target=None,
        chosen={"skill": "paper_reader"},
        rejected={"skill": "citation_manager"},
    )
    assert preference.learning_method == "preference"


def test_private_data_requires_explicit_consent_and_anonymization() -> None:
    with pytest.raises(ValidationError):
        sample(
            source="private_conversation",
            privacy=PrivacyLabel.PRIVATE_AUTHORIZED,
            consent_id=None,
            anonymized=False,
        )

    allowed = sample(
        source="private_conversation",
        privacy=PrivacyLabel.PRIVATE_AUTHORIZED,
        consent_id="consent-001",
        anonymized=True,
    )
    assert allowed.consent_id == "consent-001"


def test_dataset_validation_blocks_paper_and_conversation_split_leakage(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text(
        "\n".join(
            [
                sample().model_dump_json(),
                sample(
                    sample_id="router-002",
                    dataset_split=DatasetSplit.TEST,
                    sft_target={"intent": "paper_qa"},
                ).model_dump_json(),
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(DatasetValidationError, match="split leakage"):
        validate_dataset(dataset)


def test_dataset_manifest_is_content_addressed(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text(sample().model_dump_json() + "\n", encoding="utf-8")

    result = validate_dataset(dataset)
    manifest = DatasetManifest.from_validation(
        dataset_version="router-v1",
        task_type="router",
        source_path=dataset,
        validation=result,
    )

    assert manifest.sha256
    assert manifest.sample_count == 1
    assert manifest.split_counts == {"train": 1}


def test_training_package_has_no_runtime_or_infrastructure_imports() -> None:
    forbidden = {
        "agent_runtime",
        "apps",
        "conversations",
        "infrastructure",
        "memory",
        "tasks",
        "workspace",
    }
    imported: set[str] = set()
    for path in (ROOT / "training").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".", 1)[0])

    assert not (imported & forbidden)


def test_training_cli_validates_exported_bundle_without_services() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "training",
            "validate",
            "--bundle",
            "training/exported",
            "--dataset",
            "training/fixtures/router.sample.jsonl",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["bundle_version"] == "stage-j-v1"
    assert payload["sample_count"] == 3
