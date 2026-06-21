"""Typed task-specific training profile catalog."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class TrainingProfile(BaseModel):
    family: str
    methods: list[str] = Field(min_length=1)
    start_samples: tuple[int, int]
    target_samples: tuple[int, int]
    gates: dict[str, float | int | bool]

    @property
    def minimum_samples(self) -> int:
        return self.start_samples[0]


def load_profile_catalog(path: Path) -> dict[str, TrainingProfile]:
    raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("schema_version") != "1.0":
        raise ValueError("unsupported training profile catalog")
    profiles = raw.get("profiles")
    if not isinstance(profiles, dict):
        raise ValueError("training profile catalog has no profiles")
    return {
        str(name): TrainingProfile.model_validate(payload)
        for name, payload in profiles.items()
    }
