"""Versioned offline training-data contracts."""

from __future__ import annotations

import hashlib
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class DatasetSplit(StrEnum):
    TRAIN = "train"
    VALIDATION = "validation"
    TEST = "test"


class PrivacyLabel(StrEnum):
    SYNTHETIC = "synthetic"
    PUBLIC = "public"
    PRIVATE_AUTHORIZED = "private_authorized"


class TrainingSample(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    sample_id: str = Field(min_length=1)
    task_type: str = Field(min_length=1)
    source: str = Field(min_length=1)
    base_model_family: str = Field(min_length=1)
    input: dict[str, Any]
    tools: list[dict[str, Any]]
    context: dict[str, Any]
    sft_target: dict[str, Any] | str | None = None
    chosen: dict[str, Any] | str | None = None
    rejected: dict[str, Any] | str | None = None
    automatic_validation: dict[str, bool | float | int | str] = Field(
        default_factory=dict
    )
    human_review_status: Literal["pending", "approved", "rejected"]
    dataset_split: DatasetSplit
    paper_ids: list[str] = Field(min_length=1)
    conversation_ids: list[str] = Field(min_length=1)
    license: str = Field(min_length=1)
    privacy: PrivacyLabel
    consent_id: str | None = None
    anonymized: bool = False

    @model_validator(mode="after")
    def validate_learning_target_and_privacy(self) -> TrainingSample:
        has_sft = self.sft_target is not None
        has_chosen = self.chosen is not None
        has_rejected = self.rejected is not None
        if has_sft == (has_chosen and has_rejected):
            raise ValueError("provide exactly one SFT target or one preference pair")
        if has_chosen != has_rejected:
            raise ValueError("chosen and rejected must be supplied together")
        if self.privacy is PrivacyLabel.PRIVATE_AUTHORIZED:
            if not self.consent_id or not self.anonymized:
                raise ValueError(
                    "authorized private data requires consent_id and anonymized=true"
                )
        elif self.consent_id is not None:
            raise ValueError("consent_id is only valid for authorized private data")
        return self

    @property
    def learning_method(self) -> Literal["sft", "preference"]:
        return "sft" if self.sft_target is not None else "preference"


class DatasetValidation(BaseModel):
    sample_count: int
    split_counts: dict[str, int]
    learning_method_counts: dict[str, int]
    privacy_counts: dict[str, int]
    sha256: str


class DatasetManifest(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    dataset_version: str
    task_type: str
    source_file: str
    sha256: str
    sample_count: int
    split_counts: dict[str, int]
    learning_method_counts: dict[str, int]
    privacy_counts: dict[str, int]

    @classmethod
    def from_validation(
        cls,
        *,
        dataset_version: str,
        task_type: str,
        source_path: Path,
        validation: DatasetValidation,
    ) -> DatasetManifest:
        return cls(
            dataset_version=dataset_version,
            task_type=task_type,
            source_file=source_path.name,
            **validation.model_dump(),
        )


class ExportedBundleManifest(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    bundle_version: str
    agent_schema: str
    tool_definitions: str
    training_sample_schema: str
    checksums: dict[str, str]

    def validate_files(self, root: Path) -> None:
        for relative_path, expected in self.checksums.items():
            path = root / relative_path
            if not path.is_file():
                raise ValueError(f"missing exported contract: {relative_path}")
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual != expected:
                raise ValueError(f"checksum mismatch: {relative_path}")
