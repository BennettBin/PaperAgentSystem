"""Versioned, fail-closed baseline configuration for comparable evaluations."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class BaselineKind(StrEnum):
    VANILLA_RAG = "vanilla_rag"
    FIXED_WORKFLOW = "fixed_workflow"
    BOUNDED_REACT = "bounded_react"
    FULL_4B = "full_4b"


class EvaluationTruthClass(StrEnum):
    UNIT_FAKE = "unit_fake"
    INTEGRATION_REAL = "integration_real"
    OFFLINE_REAL_MODEL = "offline_real_model"
    HUMAN_REVIEW = "human_review"


class BaselineExecution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer_profile: str = Field(min_length=1)
    decision_profile: str | None = None
    routing: Literal["none", "rules", "bounded_react", "full_4b"]
    planning: Literal["none", "fixed", "bounded_react"]
    retrieval: Literal["none", "hybrid"]
    verification: Literal["citation_ids", "deterministic"]
    multi_agent: bool = False
    max_steps: int = Field(ge=1, le=20)
    max_replans: int = Field(ge=0, le=2)


class BaselineRetrieval(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pipeline: list[str] = Field(min_length=1)
    candidate_limit: int = Field(ge=1)
    final_limit: int = Field(ge=1)
    section_resolution: bool


class BaselineConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"]
    baseline_id: str = Field(pattern=r"^b[0-3]_[a-z0-9_]+$")
    label: str = Field(min_length=1)
    kind: BaselineKind
    frozen: Literal[True]
    description: str = Field(min_length=20)
    execution: BaselineExecution
    retrieval: BaselineRetrieval
    prompt_versions: dict[str, str] = Field(min_length=1)
    allowed_truth_classes: set[EvaluationTruthClass] = Field(min_length=1)
    effect_metric_truth_classes: set[EvaluationTruthClass] = Field(min_length=1)
    effect_metrics_require_real_model: Literal[True]

    @model_validator(mode="after")
    def validate_truth_gate(self) -> "BaselineConfig":
        if not self.effect_metric_truth_classes <= self.allowed_truth_classes:
            raise ValueError("effect metric truth classes must be allowed")
        if EvaluationTruthClass.UNIT_FAKE in self.effect_metric_truth_classes:
            raise ValueError("unit_fake cannot support effect metrics")
        if (
            EvaluationTruthClass.OFFLINE_REAL_MODEL
            not in self.effect_metric_truth_classes
        ):
            raise ValueError("effect metrics require offline_real_model evidence")
        return self

    @property
    def config_hash(self) -> str:
        normalized = self.model_dump(mode="json")
        normalized["allowed_truth_classes"] = sorted(
            normalized["allowed_truth_classes"]
        )
        normalized["effect_metric_truth_classes"] = sorted(
            normalized["effect_metric_truth_classes"]
        )
        payload = json.dumps(
            normalized,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()


def load_baseline(path: Path) -> BaselineConfig:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"baseline must be a mapping: {path}")
    return BaselineConfig.model_validate(payload)


def load_baselines(directory: Path) -> list[BaselineConfig]:
    if not directory.is_dir():
        raise FileNotFoundError(f"baseline directory not found: {directory}")
    baselines = [load_baseline(path) for path in sorted(directory.glob("*.yaml"))]
    ids = [baseline.baseline_id for baseline in baselines]
    kinds = [baseline.kind for baseline in baselines]
    if len(ids) != len(set(ids)):
        raise ValueError("baseline IDs must be unique")
    if len(kinds) != len(set(kinds)):
        raise ValueError("baseline kinds must be unique")
    return baselines


def load_baseline_by_id(directory: Path, baseline_id: str) -> BaselineConfig:
    matches = [
        baseline
        for baseline in load_baselines(directory)
        if baseline.baseline_id == baseline_id
    ]
    if len(matches) != 1:
        raise ValueError(f"unknown or duplicate baseline: {baseline_id}")
    return matches[0]
