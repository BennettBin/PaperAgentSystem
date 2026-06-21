"""Evidence-grounded answers with program-assigned citations."""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field

from rag.retrieval import RetrievalHit


class PageTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_id: str
    page_number: int = Field(ge=1)
    bbox: tuple[float, float, float, float]


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    citation_id: str = Field(pattern=r"^C\d+$")
    chunk_id: str
    quote: str
    target: PageTarget


class AnswerClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    citation_ids: list[str] = Field(min_length=1)


class CitedAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str
    claims: list[AnswerClaim]
    citations: list[Citation]
    answerable: bool
    refusal_reason: str | None = None


class ClaimEvidenceChecker:
    def supported(
        self,
        claim: str,
        citations: list[Citation],
        citation_ids: list[str],
    ) -> bool:
        evidence = " ".join(
            citation.quote
            for citation in citations
            if citation.citation_id in citation_ids
        )
        claim_terms = set(_meaningful_terms(claim))
        evidence_terms = set(_meaningful_terms(evidence))
        if not claim_terms:
            return False
        return len(claim_terms & evidence_terms) / len(claim_terms) >= 0.8


class CitationAnswerService:
    def __init__(
        self,
        checker: ClaimEvidenceChecker | None = None,
        *,
        minimum_query_coverage: float = 0.5,
    ) -> None:
        self._checker = checker or ClaimEvidenceChecker()
        self._minimum_query_coverage = minimum_query_coverage

    def answer(self, question: str, hits: list[RetrievalHit]) -> CitedAnswer:
        query_terms = set(_meaningful_terms(question))
        ranked_sentences = []
        for hit in hits:
            for sentence in _sentences(hit.text):
                terms = set(_meaningful_terms(sentence))
                coverage = len(query_terms & terms) / max(1, len(query_terms))
                ranked_sentences.append((coverage, sentence, hit))
        ranked_sentences.sort(
            key=lambda item: (-item[0], -item[2].score, item[2].chunk_id)
        )
        selected = [
            item for item in ranked_sentences if item[0] >= self._minimum_query_coverage
        ][:3]
        if not selected:
            return CitedAnswer(
                answer="现有证据不足，无法可靠回答该问题。",
                claims=[],
                citations=[],
                answerable=False,
                refusal_reason="insufficient_evidence",
            )
        citations = [
            Citation(
                citation_id=f"C{index}",
                chunk_id=hit.chunk_id,
                quote=sentence,
                target=PageTarget(
                    file_id=hit.file_id,
                    page_number=hit.page_start,
                    bbox=hit.bbox,
                ),
            )
            for index, (_, sentence, hit) in enumerate(selected, start=1)
        ]
        claims = [
            AnswerClaim(text=sentence, citation_ids=[citation.citation_id])
            for (_, sentence, _), citation in zip(selected, citations)
        ]
        supported = [
            claim
            for claim in claims
            if self._checker.supported(claim.text, citations, claim.citation_ids)
        ]
        if len(supported) != len(claims):
            return CitedAnswer(
                answer="候选答案未通过证据支持检查，无法可靠回答。",
                claims=[],
                citations=[],
                answerable=False,
                refusal_reason="claim_evidence_check_failed",
            )
        answer = " ".join(
            f"{claim.text} [{claim.citation_ids[0]}]" for claim in claims
        )
        return CitedAnswer(
            answer=answer,
            claims=claims,
            citations=citations,
            answerable=True,
        )


def _sentences(text: str) -> list[str]:
    return [
        sentence.strip()
        for sentence in re.split(r"(?<=[。！？.!?])\s+|\n+", text)
        if sentence.strip()
    ]


def _meaningful_terms(text: str) -> list[str]:
    stopwords = {
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "what",
        "which",
        "how",
        "does",
        "did",
        "of",
        "in",
        "to",
        "and",
        "该",
        "的",
        "是",
        "什么",
        "如何",
    }
    return [
        term
        for term in re.findall(r"[a-z0-9%]+|[\u4e00-\u9fff]{2,}", text.casefold())
        if term not in stopwords
    ]
