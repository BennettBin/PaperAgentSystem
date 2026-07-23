"""Strict, provenance-aware contracts for trustworthy evaluation datasets."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TaskDifficulty(StrEnum):
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"
    L4 = "L4"
    L5 = "L5"
    L6 = "L6"


class DatasetSplit(StrEnum):
    TRAIN = "train"
    VALIDATION = "validation"
    TEST = "test"


class EvaluationLanguage(StrEnum):
    ZH = "zh"
    EN = "en"
    MIXED = "mixed"


class AuthorizationStatus(StrEnum):
    PUBLIC = "public"
    OWNED = "owned"
    LICENSED = "licensed"
    PRIVATE_CONSENTED = "private_consented"
    UNAUTHORIZED = "unauthorized"


class JudgeType(StrEnum):
    PROGRAMMATIC = "programmatic"
    LLM = "llm"
    HUMAN = "human"


class JudgeVerdict(StrEnum):
    PASS = "pass"
    PARTIAL = "partial"
    FAIL = "fail"
    ABSTAIN = "abstain"


class SourceRecord(StrictModel):
    source_id: str = Field(min_length=1)
    source_cluster_id: str = Field(min_length=1)
    authorization_status: AuthorizationStatus
    license: str = Field(min_length=1)
    provenance_uri: str = Field(min_length=1)
    build_version: str = Field(min_length=1)
    consent_id: str | None = None

    @model_validator(mode="after")
    def validate_authorization(self) -> SourceRecord:
        if self.authorization_status is AuthorizationStatus.UNAUTHORIZED:
            raise ValueError("evaluation sources must be authorized")
        if (
            self.authorization_status is AuthorizationStatus.PRIVATE_CONSENTED
            and not self.consent_id
        ):
            raise ValueError("private evaluation data requires an explicit consent_id")
        return self


class ResourceBudget(StrictModel):
    max_model_calls: int = Field(ge=0)
    max_tool_calls: int = Field(ge=0)
    max_input_tokens: int = Field(ge=0)
    max_output_tokens: int = Field(ge=0)
    max_latency_ms: int = Field(gt=0)
    max_gpu_seconds: float | None = Field(default=None, ge=0)
    max_monetary_cost: float | None = Field(default=None, ge=0)


class EvidenceGold(StrictModel):
    evidence_id: str = Field(min_length=1)
    paper_id: str = Field(min_length=1)
    span_text: str = Field(min_length=1)
    page_number: int = Field(ge=1)
    section: str = Field(min_length=1)
    claim_ids: list[str] = Field(min_length=1)


class ExpectedTrajectory(StrictModel):
    required_steps: list[str] = Field(default_factory=list)
    allowed_alternative_paths: list[list[str]] = Field(default_factory=list)
    forbidden_tool_calls: list[str] = Field(default_factory=list)
    required_tools: list[str] = Field(default_factory=list)


class ReferenceAnswer(StrictModel):
    answer: str = Field(min_length=1)
    claims: list[str] = Field(default_factory=list)
    acceptable_variants: list[str] = Field(default_factory=list)
    requires_human_judge: bool = False


class DeduplicationRecord(StrictModel):
    text_fingerprint: str = Field(min_length=1)
    embedding_cluster_id: str = Field(min_length=1)
    paper_source_cluster_id: str = Field(min_length=1)


class JudgeResult(StrictModel):
    case_id: str = Field(min_length=1)
    judge_type: JudgeType
    verdict: JudgeVerdict
    scores: dict[str, float] = Field(default_factory=dict)
    reason_summary: str = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)
    judge_profile: str | None = None
    judge_version: str = Field(min_length=1)
    repetition: int = Field(default=1, ge=1)


class EvaluationCase(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    case_id: str = Field(min_length=1)
    task_family: str = Field(min_length=1)
    difficulty: TaskDifficulty
    split: DatasetSplit
    language: EvaluationLanguage
    paper_type: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    paper_ids: list[str] = Field(default_factory=list)
    conversation_ids: list[str] = Field(default_factory=list)
    source: SourceRecord
    expected_tools: list[str] = Field(default_factory=list)
    required_evidence: list[EvidenceGold] = Field(default_factory=list)
    expected_trajectory: ExpectedTrajectory | None = None
    reference_answer: ReferenceAnswer | None = None
    unacceptable_behaviors: list[str] = Field(min_length=1)
    resource_budget: ResourceBudget
    requires_evidence: bool = False
    usable_for_training: bool = False
    deduplication: DeduplicationRecord
    tags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_case_semantics(self) -> EvaluationCase:
        paper_bound = {
            TaskDifficulty.L2,
            TaskDifficulty.L3,
            TaskDifficulty.L4,
            TaskDifficulty.L5,
        }
        if self.difficulty in paper_bound and not self.paper_ids:
            raise ValueError(f"{self.difficulty.value} cases require at least one paper_id")
        if self.difficulty in {TaskDifficulty.L4, TaskDifficulty.L5} and len(self.paper_ids) < 2:
            raise ValueError(f"{self.difficulty.value} cases require multiple papers")
        if self.requires_evidence and not self.required_evidence:
            raise ValueError("evidence-required cases must provide gold evidence")
        if self.requires_evidence and self.reference_answer is None:
            raise ValueError("evidence-required cases must provide a reference answer")
        unknown_evidence_papers = {
            evidence.paper_id for evidence in self.required_evidence
        } - set(self.paper_ids)
        if unknown_evidence_papers:
            raise ValueError("gold evidence must reference a paper declared by the case")
        if self.split is DatasetSplit.TEST and self.usable_for_training:
            raise ValueError("test cases cannot be used for training or prompt tuning")
        return self


class SplitLeakage(StrictModel):
    paper_ids: list[str] = Field(default_factory=list)
    conversation_ids: list[str] = Field(default_factory=list)
    text_fingerprints: list[str] = Field(default_factory=list)
    embedding_cluster_ids: list[str] = Field(default_factory=list)
    paper_source_cluster_ids: list[str] = Field(default_factory=list)


class DatasetBuildManifest(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    dataset_version: str = Field(min_length=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    contract_only: bool = False
    case_count: int = Field(ge=0)
    split_counts: dict[str, int]
    difficulty_counts: dict[str, int]
    task_family_counts: dict[str, int]
    traceable_case_rate: float = Field(ge=0, le=1)
    cases_sha256: str = Field(min_length=1)
    leakage: SplitLeakage
