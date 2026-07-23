"""Deterministic output verification; no generative model is required."""

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class VerificationStatus(str, Enum):
    PASSED = "passed"
    NEEDS_REPAIR = "needs_repair"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class Claim:
    text: str
    evidence_ids: tuple[str, ...] = ()
    severity: str = "normal"


@dataclass(frozen=True, slots=True)
class VerificationInput:
    output: dict[str, Any]
    required_fields: set[str]
    claims: list[Claim] = field(default_factory=list)
    valid_citation_ids: set[str] = field(default_factory=set)
    immutable_terms: set[str] = field(default_factory=set)
    source_text: str = ""


@dataclass(frozen=True, slots=True)
class VerificationIssue:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class VerificationResult:
    status: VerificationStatus
    issues: list[VerificationIssue]
    coverage: float
    repair_suggestion: str


class Verifier:
    MAX_REPAIRS = 2
    CITATION_PATTERN = re.compile(r"\[([A-Za-z]\w*)\]")
    NUMBER_PATTERN = re.compile(r"(?<!\w)\d+(?:\.\d+)?%?")

    def verify(
        self,
        item: VerificationInput,
        *,
        repair_count: int = 0,
    ) -> VerificationResult:
        issues: list[VerificationIssue] = []
        present = set(item.output)
        missing = item.required_fields - present
        if missing:
            issues.append(
                VerificationIssue("schema_missing", f"Missing fields: {sorted(missing)}")
            )
        coverage = (
            len(item.required_fields & present) / len(item.required_fields)
            if item.required_fields
            else 1.0
        )
        for claim in item.claims:
            if claim.severity == "severe" and not claim.evidence_ids:
                issues.append(
                    VerificationIssue(
                        "unsupported_severe_claim",
                        f"Severe claim has no evidence: {claim.text}",
                    )
                )
        output_text = json.dumps(item.output, ensure_ascii=False)
        output_numbers = set(self.NUMBER_PATTERN.findall(output_text))
        source_numbers = set(self.NUMBER_PATTERN.findall(item.source_text))
        unsupported_numbers = output_numbers - source_numbers
        if item.source_text and unsupported_numbers:
            issues.append(
                VerificationIssue(
                    "number_mismatch",
                    f"Numbers not found in source: {sorted(unsupported_numbers)}",
                )
            )
        citations = set(self.CITATION_PATTERN.findall(output_text))
        invalid = citations - item.valid_citation_ids
        if invalid:
            issues.append(
                VerificationIssue("invalid_citation", f"Unknown citations: {sorted(invalid)}")
            )
        missing_terms = {term for term in item.immutable_terms if term not in output_text}
        if missing_terms:
            issues.append(
                VerificationIssue(
                    "invariant_missing",
                    f"Immutable terms changed or missing: {sorted(missing_terms)}",
                )
            )
        if not issues:
            return VerificationResult(VerificationStatus.PASSED, [], coverage, "")
        if repair_count >= self.MAX_REPAIRS:
            return VerificationResult(VerificationStatus.FAILED, issues, coverage, "")
        suggestion = "; ".join(issue.message for issue in issues)
        return VerificationResult(
            VerificationStatus.NEEDS_REPAIR,
            issues,
            coverage,
            suggestion,
        )
