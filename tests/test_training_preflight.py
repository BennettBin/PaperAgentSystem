import json
from pathlib import Path

import yaml

from training.preflight import PreflightRequest, run_preflight
from training.profiles import load_profile_catalog

ROOT = Path(__file__).resolve().parents[1]


def _write_dataset(path: Path, task_type: str, count: int) -> None:
    rows = []
    for index in range(count):
        rows.append(
            {
                "schema_version": "1.0",
                "sample_id": f"{task_type}-{index}",
                "task_type": task_type,
                "source": "synthetic",
                "base_model_family": "qwen3-1.7b",
                "input": {"request": f"request-{index}"},
                "tools": [],
                "context": {},
                "sft_target": {"label": task_type},
                "chosen": None,
                "rejected": None,
                "automatic_validation": {"json_valid": True},
                "human_review_status": "approved",
                "dataset_split": "train",
                "paper_ids": [f"paper-{index}"],
                "conversation_ids": [f"conversation-{index}"],
                "license": "CC0-1.0",
                "privacy": "synthetic",
                "consent_id": None,
                "anonymized": False,
            }
        )
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_1_7b_profiles_are_separate_and_keep_documented_methods_and_gates() -> None:
    catalog = load_profile_catalog(ROOT / "training/configs/profiles.yaml")

    assert catalog["router"].family == "1.7b"
    assert catalog["skill_selector"].methods == ["qlora_sft", "dpo"]
    assert catalog["query_rewriter"].methods == ["qlora_sft", "optional_dpo"]
    assert catalog["tool_caller"].methods == ["qlora_sft", "dpo_or_grpo"]
    assert catalog["router"].gates["skill_top1"] == 0.90
    assert catalog["tool_caller"].gates["schema_validity"] == 0.99


def test_preflight_passes_only_with_dataset_model_and_dependencies(
    tmp_path: Path,
) -> None:
    dataset = tmp_path / "router.jsonl"
    _write_dataset(dataset, "router", 3)
    model = tmp_path / "model"
    model.mkdir()
    (model / "config.json").write_text("{}", encoding="utf-8")
    config = tmp_path / "profiles.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "schema_version": "1.0",
                "profiles": {
                    "router": {
                        "family": "1.7b",
                        "methods": ["qlora_sft", "dpo"],
                        "start_samples": [3, 5],
                        "target_samples": [10, 30],
                        "gates": {"skill_top1": 0.9},
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    report = run_preflight(
        PreflightRequest(
            task="router",
            dataset=dataset,
            base_model=model,
            catalog=config,
            required_modules=("json", "pydantic"),
            minimum_vram_gb=0,
        )
    )

    assert report.ready
    assert report.dataset_sample_count == 3
    assert report.checks["dataset_minimum"]
    assert report.checks["base_model"]
    assert report.checks["dependencies"]


def test_repository_j02_preflight_truthfully_reports_missing_assets() -> None:
    report = run_preflight(
        PreflightRequest(
            task="router",
            dataset=ROOT / "training/data/router/train.jsonl",
            base_model=ROOT / "models/base/qwen3-1.7b",
            catalog=ROOT / "training/configs/profiles.yaml",
        )
    )

    assert not report.ready
    assert report.checks["dataset_exists"] is False
    assert report.checks["base_model"] is False
    assert report.checks["dependencies"] is False
