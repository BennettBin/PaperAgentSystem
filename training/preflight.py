"""Fail-closed preflight for expensive model training."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from training.dataset import DatasetValidationError, validate_dataset
from training.profiles import load_profile_catalog

DEFAULT_TRAINING_MODULES = (
    "torch",
    "transformers",
    "datasets",
    "peft",
    "trl",
    "accelerate",
)


@dataclass(frozen=True, slots=True)
class PreflightRequest:
    task: str
    dataset: Path
    base_model: Path
    catalog: Path
    required_modules: tuple[str, ...] = DEFAULT_TRAINING_MODULES
    minimum_vram_gb: float = 7.0


class PreflightReport(BaseModel):
    task: str
    family: str | None
    methods: list[str]
    dataset_sample_count: int
    minimum_samples: int
    detected_vram_gb: float
    missing_modules: list[str]
    checks: dict[str, bool]
    blockers: list[str]

    @property
    def ready(self) -> bool:
        return all(self.checks.values())

    def write_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = self.model_dump(mode="json")
        payload["ready"] = self.ready
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def _detect_vram_gb() -> float:
    try:
        output = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.total",
                "--format=csv,noheader,nounits",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.splitlines()
        return max(float(item.strip()) for item in output) / 1024
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError):
        return 0.0


def run_preflight(request: PreflightRequest) -> PreflightReport:
    catalog = load_profile_catalog(request.catalog)
    profile = catalog.get(request.task)
    checks = {
        "known_task": profile is not None,
        "dataset_exists": request.dataset.is_file(),
        "dataset_valid": False,
        "dataset_minimum": False,
        "base_model": (request.base_model / "config.json").is_file(),
        "dependencies": False,
        "vram": False,
    }
    blockers: list[str] = []
    sample_count = 0
    if profile is None:
        blockers.append(f"unknown training task: {request.task}")
    if checks["dataset_exists"]:
        try:
            validation = validate_dataset(request.dataset)
            sample_count = validation.sample_count
            checks["dataset_valid"] = True
            checks["dataset_minimum"] = (
                profile is not None and sample_count >= profile.minimum_samples
            )
            if not checks["dataset_minimum"] and profile is not None:
                blockers.append(
                    f"dataset has {sample_count} samples; minimum is {profile.minimum_samples}"
                )
        except DatasetValidationError as exc:
            blockers.append(str(exc))
    else:
        blockers.append(f"dataset not found: {request.dataset}")

    if not checks["base_model"]:
        blockers.append(f"base model config not found: {request.base_model / 'config.json'}")

    missing_modules = [
        name for name in request.required_modules if importlib.util.find_spec(name) is None
    ]
    checks["dependencies"] = not missing_modules
    if missing_modules:
        blockers.append("missing training modules: " + ", ".join(missing_modules))

    detected_vram = _detect_vram_gb()
    checks["vram"] = detected_vram >= request.minimum_vram_gb
    if not checks["vram"]:
        blockers.append(
            f"detected VRAM {detected_vram:.2f} GiB; required {request.minimum_vram_gb:.2f} GiB"
        )

    return PreflightReport(
        task=request.task,
        family=profile.family if profile else None,
        methods=profile.methods if profile else [],
        dataset_sample_count=sample_count,
        minimum_samples=profile.minimum_samples if profile else 0,
        detected_vram_gb=round(detected_vram, 2),
        missing_modules=missing_modules,
        checks=checks,
        blockers=blockers,
    )
