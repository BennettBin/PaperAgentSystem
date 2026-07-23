from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from evaluation.datasets.audit import DatasetAuditError, audit_cases, load_cases
from evaluation.datasets.schema import (
    AuthorizationStatus,
    DatasetBuildManifest,
    DatasetSplit,
    DeduplicationRecord,
    EvaluationCase,
    EvidenceGold,
    ExpectedTrajectory,
    ReferenceAnswer,
    ResourceBudget,
    SourceRecord,
    TaskDifficulty,
)


def _case(
    case_id: str,
    *,
    split: DatasetSplit = DatasetSplit.TEST,
    paper_id: str | None = None,
    conversation_id: str | None = None,
    fingerprint: str | None = None,
    embedding_cluster: str | None = None,
    source_cluster: str | None = None,
) -> EvaluationCase:
    paper_id = paper_id or f"paper-{case_id}"
    conversation_id = conversation_id or f"conversation-{case_id}"
    source_cluster = source_cluster or f"source-cluster-{case_id}"
    return EvaluationCase(
        case_id=case_id,
        task_family="single_paper_qa",
        difficulty=TaskDifficulty.L2,
        split=split,
        language="zh",
        paper_type="double_column",
        prompt="论文使用了什么优化器？",
        paper_ids=[paper_id],
        conversation_ids=[conversation_id],
        source=SourceRecord(
            source_id=f"source-{case_id}",
            source_cluster_id=source_cluster,
            authorization_status=AuthorizationStatus.PUBLIC,
            license="CC-BY-4.0",
            provenance_uri="https://example.org/paper",
            build_version="evaluation-v1",
        ),
        expected_tools=["paper_search"],
        required_evidence=[
            EvidenceGold(
                evidence_id="gold-e1",
                paper_id=paper_id,
                span_text="We optimize with AdamW.",
                page_number=3,
                section="Methods",
                claim_ids=["claim-1"],
            )
        ],
        reference_answer=ReferenceAnswer(
            answer="论文使用 AdamW。",
            claims=["论文使用 AdamW。"],
        ),
        expected_trajectory=ExpectedTrajectory(
            required_steps=["resolve_paper", "retrieve", "answer_with_citation"],
            allowed_alternative_paths=[
                ["resolve_paper", "section_retrieve", "answer_with_citation"]
            ],
            forbidden_tool_calls=["web_search"],
        ),
        unacceptable_behaviors=["unsupported_claim", "cross_workspace_access"],
        resource_budget=ResourceBudget(
            max_model_calls=3,
            max_tool_calls=4,
            max_input_tokens=12_000,
            max_output_tokens=1_500,
            max_latency_ms=30_000,
        ),
        requires_evidence=True,
        usable_for_training=False,
        deduplication=DeduplicationRecord(
            text_fingerprint=fingerprint or f"sha256-{case_id}",
            embedding_cluster_id=embedding_cluster or f"embedding-{case_id}",
            paper_source_cluster_id=source_cluster,
        ),
    )


def test_case_rejects_missing_gold_evidence_and_unauthorized_source() -> None:
    payload = _case("case-valid").model_dump(mode="json")
    payload["required_evidence"] = []
    with pytest.raises(ValidationError, match="gold evidence"):
        EvaluationCase.model_validate(payload)

    payload = _case("case-valid").model_dump(mode="json")
    payload["source"]["authorization_status"] = "unauthorized"
    with pytest.raises(ValidationError, match="authorized"):
        EvaluationCase.model_validate(payload)


def test_case_rejects_unknown_split_and_training_use_of_test_data() -> None:
    payload = _case("case-valid").model_dump(mode="json")
    payload["split"] = "holdout"
    with pytest.raises(ValidationError):
        EvaluationCase.model_validate(payload)

    payload = _case("case-valid").model_dump(mode="json")
    payload["usable_for_training"] = True
    with pytest.raises(ValidationError, match="test cases"):
        EvaluationCase.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("paper_id", "paper-shared", "paper_id"),
        ("conversation_id", "conversation-shared", "conversation_id"),
        ("fingerprint", "sha256-shared", "text fingerprint"),
        ("embedding_cluster", "embedding-shared", "embedding near-duplicate"),
        ("source_cluster", "source-shared", "paper source"),
    ],
)
def test_group_split_and_near_duplicate_leakage_fail_closed(
    field: str, value: str, message: str
) -> None:
    train_kwargs = {field: value}
    test_kwargs = {field: value}
    cases = [
        _case("train-case", split=DatasetSplit.TRAIN, **train_kwargs),
        _case("test-case", split=DatasetSplit.TEST, **test_kwargs),
    ]

    with pytest.raises(DatasetAuditError, match=message):
        audit_cases(cases, dataset_version="evaluation-v1")


def test_audit_manifest_is_traceable_and_has_zero_leakage() -> None:
    cases = [
        _case(
            "train-case",
            split=DatasetSplit.TRAIN,
            paper_id="paper-train",
            conversation_id="conversation-train",
            source_cluster="source-train",
        ),
        _case(
            "validation-case",
            split=DatasetSplit.VALIDATION,
            paper_id="paper-validation",
            conversation_id="conversation-validation",
            source_cluster="source-validation",
        ),
        _case(
            "test-case",
            split=DatasetSplit.TEST,
            paper_id="paper-test",
            conversation_id="conversation-test",
            source_cluster="source-test",
        ),
    ]

    manifest = audit_cases(cases, dataset_version="evaluation-v1")

    assert manifest.case_count == 3
    assert manifest.split_counts == {"test": 1, "train": 1, "validation": 1}
    assert manifest.traceable_case_rate == 1.0
    assert manifest.leakage.paper_ids == []
    assert manifest.leakage.conversation_ids == []
    assert manifest.leakage.text_fingerprints == []
    assert manifest.leakage.embedding_cluster_ids == []
    assert manifest.leakage.paper_source_cluster_ids == []
    assert DatasetBuildManifest.model_validate(manifest.model_dump()) == manifest


def test_jsonl_loader_rejects_private_unconsented_case(tmp_path: Path) -> None:
    payload = _case("private-case").model_dump(mode="json")
    payload["source"]["authorization_status"] = "private_consented"
    payload["source"]["consent_id"] = None
    path = tmp_path / "cases.jsonl"
    path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")

    with pytest.raises(DatasetAuditError, match="line 1"):
        load_cases(path)
