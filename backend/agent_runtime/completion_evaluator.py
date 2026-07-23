"""Programmatic completion and evidence-sufficiency evaluation."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from backend.agent_runtime.planner import (
    EvidenceRequirement,
    Observation,
    ObservationStatus,
    PlanStep,
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvidenceRecord(_StrictModel):
    evidence_id: str = Field(min_length=1)
    source_id: str = ""
    page_number: int | None = None
    claim_ids: list[str] = Field(default_factory=list)
    trusted: bool = True


class ClaimEvidence(_StrictModel):
    claim_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)
    factual: bool = True


class NumericCheck(_StrictModel):
    claim_id: str = Field(min_length=1)
    value: str = Field(min_length=1)
    verified: bool = False
    evidence_id: str | None = None


class CompletionEvaluationInput(_StrictModel):
    output: dict[str, Any]
    tool_succeeded: bool = True
    artifact_ref: str | None = None
    claims: list[ClaimEvidence] = Field(default_factory=list)
    evidence: list[EvidenceRecord] = Field(default_factory=list)
    target_paper_ids: list[str] = Field(default_factory=list)
    immutable_terms: list[str] = Field(default_factory=list)
    numeric_checks: list[NumericCheck] = Field(default_factory=list)
    review_required: bool = False
    requires_user_input: bool = False
    fatal_error: str | None = None
    repair_attempts: int = Field(default=0, ge=0)
    max_repairs: int = Field(default=2, ge=0)
    can_replan: bool = True


class CompletionEvaluation(_StrictModel):
    decision: ObservationStatus
    missing_items: list[str]
    quality_signal: dict[str, float | int | bool | str]
    observation: Observation


class CompletionEvaluator:
    """Judge semantic completion instead of treating transport success as completion."""

    def evaluate(
        self,
        step: PlanStep,
        item: CompletionEvaluationInput,
    ) -> CompletionEvaluation:
        predicate = step.completion_predicate
        missing: list[str] = []
        if not item.output:
            missing.append("output:non_empty")

        required_fields = predicate.required_fields if predicate else []
        present_fields = sum(_is_present(item.output.get(name)) for name in required_fields)
        missing.extend(
            f"field:{name}"
            for name in required_fields
            if not _is_present(item.output.get(name))
        )

        evidence_by_id = {record.evidence_id: record for record in item.evidence}
        valid_evidence = {
            record.evidence_id: record
            for record in item.evidence
            if record.trusted
            and bool(record.source_id.strip())
            and record.page_number is not None
            and record.page_number >= 1
        }
        for record in item.evidence:
            if not record.source_id.strip():
                missing.append(f"evidence:{record.evidence_id}:source")
            if record.page_number is None or record.page_number < 1:
                missing.append(f"evidence:{record.evidence_id}:page")
            if not record.trusted:
                missing.append(f"evidence:{record.evidence_id}:untrusted")

        factual_claims = [claim for claim in item.claims if claim.factual]
        covered_claims = 0
        referenced_evidence: set[str] = set()
        for claim in factual_claims:
            linked = [
                valid_evidence[evidence_id]
                for evidence_id in claim.evidence_ids
                if evidence_id in valid_evidence
                and claim.claim_id in valid_evidence[evidence_id].claim_ids
            ]
            if linked:
                covered_claims += 1
                referenced_evidence.update(record.evidence_id for record in linked)
            elif not claim.evidence_ids:
                missing.append(f"claim:{claim.claim_id}:missing_evidence")
            else:
                for evidence_id in claim.evidence_ids:
                    linked_record = evidence_by_id.get(evidence_id)
                    if linked_record is None or evidence_id not in valid_evidence:
                        missing.append(
                            f"claim:{claim.claim_id}:invalid_evidence:{evidence_id}"
                        )
                    elif claim.claim_id not in linked_record.claim_ids:
                        missing.append(
                            f"claim:{claim.claim_id}:unlinked_evidence:{evidence_id}"
                        )

        minimum_evidence = predicate.minimum_evidence if predicate else 0
        evidence_required = (
            step.evidence_requirement is EvidenceRequirement.REQUIRED
            or minimum_evidence > 0
        )
        usable_evidence_ids = referenced_evidence or set(valid_evidence)
        if evidence_required and len(usable_evidence_ids) < max(1, minimum_evidence):
            missing.append(f"evidence:minimum:{max(1, minimum_evidence)}")

        kind = predicate.kind.casefold() if predicate else ""
        action = step.action.casefold()
        is_comparison = "compar" in kind or "compar" in action or "aggregate" in kind
        covered_papers = {
            record.source_id for record in valid_evidence.values() if record.source_id
        }
        raw_covered = item.output.get("covered_paper_ids", [])
        if isinstance(raw_covered, list):
            covered_papers.update(str(value) for value in raw_covered)
        if is_comparison:
            missing.extend(
                f"paper:{paper_id}"
                for paper_id in item.target_paper_ids
                if paper_id not in covered_papers
            )

        verified_numbers = sum(check.verified for check in item.numeric_checks)
        for check in item.numeric_checks:
            if not check.verified:
                missing.append(f"numeric_claim:{check.claim_id}")
            elif check.evidence_id and check.evidence_id not in valid_evidence:
                missing.append(f"numeric_claim:{check.claim_id}:invalid_evidence")

        is_writing = any(marker in kind or marker in action for marker in ("writ", "draft"))
        mapped_claims = _mapped_claim_ids(item.output.get("evidence_map"))
        if is_writing:
            missing.extend(
                f"evidence_map:{claim.claim_id}"
                for claim in factual_claims
                if claim.claim_id not in mapped_claims
            )
            output_text = json.dumps(item.output, ensure_ascii=False)
            missing.extend(
                f"immutable_term:{term}"
                for term in item.immutable_terms
                if term not in output_text
            )
            if item.review_required and item.output.get("pending_review") is not True:
                missing.append("pending_review")

        if predicate and predicate.minimum_quality is not None:
            quality = item.output.get("quality_score")
            if not isinstance(quality, (int, float)) or quality < predicate.minimum_quality:
                missing.append(f"quality:minimum:{predicate.minimum_quality}")

        if item.requires_user_input:
            missing.append("user_input:required")
        if item.fatal_error:
            missing.append(f"fatal:{item.fatal_error}")
        if not item.tool_succeeded:
            missing.append("tool:failed")
        missing = list(dict.fromkeys(missing))

        decision = _decision(item, missing)
        quality_signal: dict[str, float | int | bool | str] = {
            "tool_succeeded": item.tool_succeeded,
            "schema_coverage": _ratio(present_fields, len(required_fields)),
            "claim_evidence_coverage": _ratio(covered_claims, len(factual_claims)),
            "valid_evidence_rate": _ratio(len(valid_evidence), len(item.evidence)),
            "target_paper_coverage": _ratio(
                len(set(item.target_paper_ids) & covered_papers),
                len(set(item.target_paper_ids)),
            ),
            "numeric_verification_rate": _ratio(
                verified_numbers, len(item.numeric_checks)
            ),
            "evidence_map_coverage": _ratio(
                len({claim.claim_id for claim in factual_claims} & mapped_claims),
                len(factual_claims),
            ),
            "missing_count": len(missing),
        }
        observation = Observation(
            step_id=step.step_id,
            status=decision,
            data_ref=item.artifact_ref,
            evidence_refs=sorted(usable_evidence_ids),
            error_code="completion_predicate_failed" if missing else None,
            retryable=decision is ObservationStatus.REPAIR,
            quality_signal=quality_signal,
            missing_items=missing,
        )
        return CompletionEvaluation(
            decision=decision,
            missing_items=missing,
            quality_signal=quality_signal,
            observation=observation,
        )


def _decision(
    item: CompletionEvaluationInput,
    missing: list[str],
) -> ObservationStatus:
    if item.fatal_error:
        return ObservationStatus.FAIL
    if item.requires_user_input:
        return ObservationStatus.ASK_USER
    if not item.tool_succeeded:
        return ObservationStatus.REPLAN if item.can_replan else ObservationStatus.FAIL
    if not missing:
        return ObservationStatus.COMPLETE
    if item.repair_attempts < item.max_repairs:
        return ObservationStatus.REPAIR
    return ObservationStatus.REPLAN if item.can_replan else ObservationStatus.FAIL


def _is_present(value: Any) -> int:
    return int(value is not None and value != "" and value != [] and value != {})


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 1.0


def _mapped_claim_ids(value: Any) -> set[str]:
    if isinstance(value, dict):
        return {str(key) for key, evidence in value.items() if _is_present(evidence)}
    if isinstance(value, list):
        return {
            str(entry.get("claim_id"))
            for entry in value
            if isinstance(entry, dict)
            and entry.get("claim_id")
            and _is_present(entry.get("evidence_ids"))
        }
    return set()
