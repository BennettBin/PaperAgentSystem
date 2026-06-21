"""Reproducibility metadata discovery for evaluation reports."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Any

import yaml

from evaluation.schema import EvaluationMetadata


def _yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _commit(root: Path) -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def discover_metadata(root: Path) -> EvaluationMetadata:
    registry = _yaml(root / "models" / "registry.yaml")
    profiles = {
        str(item["name"]): str(item["model_version_id"])
        for item in registry.get("profiles", [])
        if isinstance(item, dict) and "name" in item and "model_version_id" in item
    }
    skills: dict[str, str] = {}
    prompts: dict[str, str] = {}
    for manifest_path in sorted((root / "skills").glob("*/manifest.yaml")):
        manifest = _yaml(manifest_path)
        name = str(manifest.get("name", manifest_path.parent.name))
        skills[name] = str(manifest.get("version", "unversioned"))
        instruction = manifest_path.parent / "SKILL.md"
        if instruction.exists():
            digest = hashlib.sha256(instruction.read_bytes()).hexdigest()
            prompts[name] = f"sha256:{digest}"

    datasets = {
        "pdf_structure": "pdf-corpus-v1",
        "requirement_clarification": "clarification-fixtures-v1",
        "skill_selection": "skill-routing-fixtures-v1",
        "planner": "planner-fixtures-v1",
        "security": "security-attack-fixtures-v1",
        "domain_quality": "academic-task-fixtures-v1",
        "final_e2e": "stage-i-scenarios-v1",
    }
    return EvaluationMetadata(
        commit=_commit(root),
        config={
            "registry": "models/registry.yaml",
            "default_profile": registry.get("default_profile", "unavailable"),
            "report_schema": "1.0",
        },
        profiles=profiles,
        skills=skills,
        datasets=datasets,
        prompts=prompts,
    )
