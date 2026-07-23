from __future__ import annotations

import json
from pathlib import Path

from evaluation.baseline_evaluation import (
    BaselineCaseScore,
    BaselineEvaluationReport,
    InMemoryHybridRetriever,
    OfflineBaselineExecutor,
    PageRecord,
    RealModelGateway,
    build_l05_report,
    token_f1,
)
from evaluation.baselines import EvaluationTruthClass, load_baseline_by_id
from evaluation.experiments import ExperimentCase


class StubRealGateway(RealModelGateway):
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def complete(
        self, *, model: str, profile: str, prompt: str, max_tokens: int
    ) -> tuple[str, int, int, int]:
        self.calls.append((model, profile))
        if profile.endswith("decision-v1"):
            return '{"action":"retrieve","query":"method"}', 12, 8, 2
        return '{"answer":"Yes.","citations":["E1"]}', 20, 10, 3


def _case_payload() -> dict:
    return {
        "schema_version": "1.0",
        "case_id": "l2-001",
        "task_family": "single_paper_qa",
        "difficulty": "L2",
        "split": "test",
        "language": "en",
        "paper_type": "single_column",
        "prompt": "Does the method use attention?",
        "paper_ids": ["paper-1"],
        "conversation_ids": [],
        "source": {
            "source_id": "s1",
            "source_cluster_id": "sc1",
            "authorization_status": "public",
            "license": "CC-BY-4.0",
            "provenance_uri": "https://example.test",
            "build_version": "v1",
        },
        "expected_tools": ["retrieve_chunks", "answer_with_citations"],
        "required_evidence": [
            {
                "evidence_id": "gold-1",
                "paper_id": "paper-1",
                "span_text": "The method uses attention.",
                "page_number": 2,
                "section": "Method",
                "claim_ids": ["claim-1"],
            }
        ],
        "expected_trajectory": {
            "required_steps": ["retrieve", "answer"],
            "required_tools": ["retrieve_chunks"],
        },
        "reference_answer": {
            "answer": "Yes.",
            "claims": ["Yes."],
            "acceptable_variants": [],
            "requires_human_judge": False,
        },
        "unacceptable_behaviors": ["unsupported_answer"],
        "resource_budget": {
            "max_model_calls": 3,
            "max_tool_calls": 2,
            "max_input_tokens": 8000,
            "max_output_tokens": 800,
            "max_latency_ms": 15000,
        },
        "requires_evidence": True,
        "usable_for_training": False,
        "deduplication": {
            "text_fingerprint": "fp1",
            "embedding_cluster_id": "ec1",
            "paper_source_cluster_id": "pc1",
        },
        "tags": [],
    }


def test_in_memory_retriever_ranks_real_pages_without_gold_input() -> None:
    retriever = InMemoryHybridRetriever(
        [
            PageRecord(paper_id="paper-1", page_number=1, section="Intro", text="Background only."),
            PageRecord(paper_id="paper-1", page_number=2, section="Method", text="The method uses attention."),
        ]
    )
    hits = retriever.retrieve("method attention", {"paper-1"}, limit=2)
    assert hits[0].page_number == 2
    assert hits[0].evidence_id == "E1"


def test_bounded_react_uses_real_small_decision_and_large_answer_profiles() -> None:
    root = Path(__file__).resolve().parents[1]
    baseline = load_baseline_by_id(root / "evaluation" / "baselines", "b2_bounded_react")
    gateway = StubRealGateway()
    executor = OfflineBaselineExecutor(
        baseline=baseline,
        gateway=gateway,
        retriever=InMemoryHybridRetriever(
            [PageRecord(paper_id="paper-1", page_number=2, section="Method", text="The method uses attention.")]
        ),
        small_model="qwen3:1.7b",
        large_model="qwen3.5:4b",
        model_versions={"qwen3:1.7b": "sha-small", "qwen3.5:4b": "sha-large"},
    )
    case = ExperimentCase(case_id="l2-001", payload=_case_payload())
    result = executor.execute(case, seed=1, attempt=1)

    assert gateway.calls == [
        ("qwen3:1.7b", "development-decision-v1"),
        ("qwen3.5:4b", "evaluation-answer-v1"),
    ]
    assert result.passed
    assert result.output["answer"] == "Yes."
    assert result.output["score"]["task_success"] is True
    assert all(call.input_tokens + call.output_tokens > 0 for call in result.model_calls)


def test_token_f1_and_report_freeze_actionable_failures_and_gates(tmp_path: Path) -> None:
    assert token_f1("Yes.", "yes") == 1.0
    scores = []
    for system in ("b0_vanilla_rag", "b1_fixed_workflow", "b2_bounded_react", "b3_full_4b"):
        for index in range(3):
            scores.append(
                BaselineCaseScore(
                    case_id=f"c-{index}",
                    system_id=system,
                    difficulty="L2",
                    task_family="single_paper_qa",
                    task_success=index == 0,
                    answer_correctness=1.0 if index == 0 else 0.0,
                    citation_recall=1.0 if index == 0 else 0.0,
                    latency_ms=100 + index,
                    input_tokens=10,
                    output_tokens=5,
                    model_calls=1,
                    four_b_calls=1,
                    error_category=None if index == 0 else ("retrieval" if index == 1 else "generation"),
                )
            )
    report = build_l05_report(scores, dataset_version="l02-v1", commit="abc")
    assert isinstance(report, BaselineEvaluationReport)
    assert report.truth_class is EvaluationTruthClass.OFFLINE_REAL_MODEL
    assert len(report.systems) == 4
    assert len(report.comparisons_to_b0) == 3
    assert report.comparisons_to_b0[0].paired_case_count == 3
    assert report.top_actionable_failures[:2] == ["generation", "retrieval"]
    assert set(report.success_gates) == {"M", "N", "O"}
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report.model_dump(mode="json"), sort_keys=True), "utf-8")
    assert path.exists()
