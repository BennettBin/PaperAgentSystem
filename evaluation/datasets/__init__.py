"""Versioned evaluation dataset contracts and audit gates."""

from evaluation.datasets.audit import DatasetAuditError, audit_cases, load_cases
from evaluation.datasets.schema import (
    AuthorizationStatus,
    DatasetBuildManifest,
    DatasetSplit,
    DeduplicationRecord,
    EvaluationCase,
    EvaluationLanguage,
    EvidenceGold,
    ExpectedTrajectory,
    JudgeResult,
    ReferenceAnswer,
    ResourceBudget,
    SourceRecord,
    TaskDifficulty,
)

__all__ = [
    "AuthorizationStatus",
    "DatasetAuditError",
    "DatasetBuildManifest",
    "DatasetSplit",
    "DeduplicationRecord",
    "EvaluationCase",
    "EvaluationLanguage",
    "EvidenceGold",
    "ExpectedTrajectory",
    "JudgeResult",
    "ReferenceAnswer",
    "ResourceBudget",
    "SourceRecord",
    "TaskDifficulty",
    "audit_cases",
    "load_cases",
]
