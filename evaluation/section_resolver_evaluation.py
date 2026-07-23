"""Metrics for the fixed 100-query section resolver benchmark."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from backend.rag.section_resolver import (
    ALIAS_VERSION,
    SectionReferenceParser,
    SectionResolver,
)
from evaluation.section_resolver_benchmark import (
    EVALUATION_CASES,
    EVALUATION_SECTIONS,
)


@dataclass(frozen=True, slots=True)
class SectionResolverMetrics:
    query_count: int
    fuzzy_threshold: float
    ambiguity_margin: float
    alias_version: str
    top1: float
    number_exact: float
    title_top1: float
    alias_top1: float
    fuzzy_top1: float
    false_forced_match: float
    unresolved_rejection: float
    ambiguity_clarification: float

    def as_dict(self) -> dict[str, str | int | float]:
        return asdict(self)


def evaluate_section_resolver(
    *,
    fuzzy_threshold: float = 0.92,
    ambiguity_margin: float = 0.06,
) -> SectionResolverMetrics:
    parser = SectionReferenceParser()
    resolver = SectionResolver(
        fuzzy_threshold=fuzzy_threshold,
        ambiguity_margin=ambiguity_margin,
    )
    outcomes = [
        (case, resolver.resolve(parser.parse(case.query), EVALUATION_SECTIONS))
        for case in EVALUATION_CASES
    ]
    positive = [
        (case, result)
        for case, result in outcomes
        if case.expected_section_id is not None
    ]

    def accuracy(category: str) -> float:
        selected = [
            (case, result)
            for case, result in outcomes
            if case.category == category
        ]
        return sum(
            result.selected is not None
            and result.selected.section_id == case.expected_section_id
            for case, result in selected
        ) / len(selected)

    negative = [
        result for case, result in outcomes if case.category == "unresolved"
    ]
    ambiguous = [
        result for case, result in outcomes if case.category == "ambiguous"
    ]
    return SectionResolverMetrics(
        query_count=len(outcomes),
        fuzzy_threshold=fuzzy_threshold,
        ambiguity_margin=ambiguity_margin,
        alias_version=ALIAS_VERSION,
        top1=sum(
            result.selected is not None
            and result.selected.section_id == case.expected_section_id
            for case, result in positive
        )
        / len(positive),
        number_exact=accuracy("number"),
        title_top1=accuracy("title"),
        alias_top1=accuracy("alias"),
        fuzzy_top1=accuracy("fuzzy"),
        false_forced_match=sum(result.status == "resolved" for result in negative)
        / len(negative),
        unresolved_rejection=sum(result.status == "unresolved" for result in negative)
        / len(negative),
        ambiguity_clarification=sum(
            result.status == "ambiguous" and bool(result.clarification_question)
            for result in ambiguous
        )
        / len(ambiguous),
    )
