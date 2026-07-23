from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import fitz

from evaluation.datasets.agreement import AnnotationPair, cohen_kappa
from evaluation.datasets.audit import audit_cases, load_cases
from evaluation.datasets.schema import TaskDifficulty

ROOT = Path(__file__).resolve().parents[1]
DATASET_ROOT = ROOT / "evaluation" / "datasets" / "v1"


def test_cohen_kappa_supports_stratified_double_annotation() -> None:
    pairs = [
        AnnotationPair(case_id="a", annotator_a_label="yes", annotator_b_label="yes"),
        AnnotationPair(case_id="b", annotator_a_label="no", annotator_b_label="no"),
        AnnotationPair(
            case_id="c",
            annotator_a_label="extractive",
            annotator_b_label="extractive",
        ),
        AnnotationPair(
            case_id="d", annotator_a_label="free_form", annotator_b_label="free_form"
        ),
    ]

    assert cohen_kappa(pairs) == 1.0


def test_fixed_l02_test_set_meets_size_distribution_and_provenance_gates() -> None:
    cases = load_cases(DATASET_ROOT / "test_cases_v1.jsonl")
    manifest = json.loads(
        (DATASET_ROOT / "dataset_manifest_v1.json").read_text(encoding="utf-8")
    )
    difficulty_counts = Counter(case.difficulty for case in cases)

    assert len(cases) == 300
    assert difficulty_counts == {
        TaskDifficulty.L1: 60,
        TaskDifficulty.L2: 60,
        TaskDifficulty.L3: 60,
        TaskDifficulty.L4: 45,
        TaskDifficulty.L5: 45,
        TaskDifficulty.L6: 30,
    }
    assert {case.language.value for case in cases} >= {"en", "zh"}
    assert all(case.split.value == "test" for case in cases)
    assert all(not case.usable_for_training for case in cases)
    assert all(case.source.provenance_uri for case in cases)
    assert all(case.source.build_version for case in cases)
    assert manifest["sources"]["qasper"]["sha256"]
    assert manifest["sources"]["csl"]["sha256"]
    assert manifest["contract_only"] is False
    assert manifest["case_count"] == 300

    audited = audit_cases(cases, dataset_version="paperagent-eval-v1")
    assert audited.traceable_case_rate == 1.0
    assert not audited.leakage.model_dump(exclude_none=True)["paper_ids"]
    assert all(not value for value in audited.leakage.model_dump().values())


def test_evidence_tasks_have_span_page_section_and_claim_support() -> None:
    cases = load_cases(DATASET_ROOT / "test_cases_v1.jsonl")
    documents = {
        document["paper_id"]: document
        for document in (
            json.loads(line)
            for line in (DATASET_ROOT / "documents_v1.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        )
    }
    evidence_cases = [case for case in cases if case.requires_evidence]

    assert evidence_cases
    assert all(case.required_evidence for case in evidence_cases)
    assert all(
        evidence.span_text
        and evidence.page_number >= 1
        and evidence.section
        and evidence.claim_ids
        for case in evidence_cases
        for evidence in case.required_evidence
    )
    assert all(
        " ".join(evidence.span_text.split())
        in " ".join(documents[evidence.paper_id]["pages"][evidence.page_number - 1]["text"].split())
        for case in evidence_cases
        for evidence in case.required_evidence
    )


def test_dataset_covers_required_languages_formats_and_robustness_conditions() -> None:
    cases = load_cases(DATASET_ROOT / "test_cases_v1.jsonl")
    tags = {tag for case in cases for tag in case.tags}
    paper_types = {case.paper_type for case in cases}

    assert {"single_column", "double_column", "degraded_scan"} <= paper_types
    assert {
        "long_paper",
        "short_paper",
        "missing_section",
        "citation_ambiguity",
        "prompt_injection",
        "tool_failure",
        "partial_failure",
        "cancellation",
        "clarification",
    } <= tags


def test_render_samples_are_real_single_double_and_scan_pdf_artifacts() -> None:
    manifest = json.loads(
        (DATASET_ROOT / "render_samples" / "manifest.json").read_text(encoding="utf-8")
    )
    assert {sample["profile"] for sample in manifest["samples"]} == {
        "single_column",
        "double_column",
        "degraded_scan",
    }
    for sample in manifest["samples"]:
        document = fitz.open(DATASET_ROOT / sample["path"])
        assert document.page_count == sample["page_count"]
        if sample["profile"] == "degraded_scan":
            assert document[0].get_images()
            assert not document[0].get_text().strip()
        else:
            assert document[0].get_text().strip()
        document.close()


def test_double_annotation_sample_is_ten_percent_and_kappa_passes() -> None:
    report = json.loads(
        (DATASET_ROOT / "annotation_agreement_v1.json").read_text(encoding="utf-8")
    )

    assert report["sample_size"] >= 30
    assert report["sample_rate"] >= 0.10
    assert report["cohen_kappa"] >= 0.80
    assert len(report["annotation_pairs"]) == report["sample_size"]
    assert report["selection_policy"] == "stratified_consensus_gold"


def test_all_metrics_can_be_sliced_by_required_dimensions() -> None:
    manifest = json.loads(
        (DATASET_ROOT / "dataset_manifest_v1.json").read_text(encoding="utf-8")
    )

    assert manifest["slice_dimensions"] == [
        "task_family",
        "difficulty",
        "language",
        "paper_type",
    ]
    for dimension in manifest["slice_dimensions"]:
        assert manifest["coverage"][dimension]
