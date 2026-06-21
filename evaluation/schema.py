"""Schemas shared by evaluation runners and report consumers."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class EvaluationSuite(StrEnum):
    CONTRACT = "contract"
    COMPONENT = "component"
    TRAJECTORY = "trajectory"
    DOMAIN = "domain"
    E2E = "e2e"
    SECURITY = "security"
    PERFORMANCE = "performance"


class EvaluationMetadata(BaseModel):
    commit: str
    config: dict[str, Any]
    profiles: dict[str, str]
    skills: dict[str, str]
    datasets: dict[str, str]
    prompts: dict[str, str] = Field(default_factory=dict)


class EvaluationResult(BaseModel):
    suite: EvaluationSuite
    passed: bool
    metrics: dict[str, float | int | str | bool] = Field(default_factory=dict)
    failures: list[str] = Field(default_factory=list)


class EvaluationReport(BaseModel):
    schema_version: str = "1.0"
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: EvaluationMetadata
    results: list[EvaluationResult]

    @property
    def passed(self) -> bool:
        return all(result.passed for result in self.results)

    def write_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = self.model_dump(mode="json")
        payload["passed"] = self.passed
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
