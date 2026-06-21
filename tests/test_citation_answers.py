from rag.citations import CitationAnswerService, ClaimEvidenceChecker
from rag.retrieval import RetrievalHit


def hit(
    text: str,
    *,
    chunk_id: str = "chunk-1",
    file_id: str = "file-1",
    score: float = 1.0,
) -> RetrievalHit:
    return RetrievalHit(
        chunk_id=chunk_id,
        workspace_id="ws-1",
        file_id=file_id,
        text=text,
        section_path=("Results",),
        page_start=3,
        page_end=3,
        bbox=(10, 20, 300, 80),
        source_block_ids=("block-1",),
        score=score,
    )


def test_answer_has_program_citations_and_page_target() -> None:
    result = CitationAnswerService().answer(
        "What accuracy did the method achieve?",
        [hit("The method achieved accuracy 95% on the benchmark.")],
    )

    assert result.answerable
    assert result.citations[0].citation_id == "C1"
    assert "[C1]" in result.answer
    assert result.citations[0].target.file_id == "file-1"
    assert result.citations[0].target.page_number == 3
    assert result.citations[0].target.bbox == (10, 20, 300, 80)


def test_unanswerable_question_is_refused() -> None:
    result = CitationAnswerService().answer(
        "What was the energy consumption?",
        [hit("The paper reports accuracy 95% on the benchmark.")],
    )

    assert not result.answerable
    assert result.citations == []
    assert result.refusal_reason == "insufficient_evidence"


def test_claim_evidence_checker_rejects_unsupported_claim() -> None:
    result = CitationAnswerService().answer(
        "What accuracy did the method achieve?",
        [hit("The method achieved accuracy 95% on the benchmark.")],
    )
    checker = ClaimEvidenceChecker()

    assert not checker.supported(
        "The method achieved accuracy 100% on every dataset.",
        result.citations,
        ["C1"],
    )


def test_citation_answer_evaluation_thresholds() -> None:
    service = CitationAnswerService()
    correct = support = severe_hallucinations = 0
    answerable_total = 80
    refused = 0
    unanswerable_total = 20
    for index in range(answerable_total):
        expected = f"{80 + index % 20}%"
        result = service.answer(
            "What accuracy did the method achieve?",
            [hit(f"The method achieved accuracy {expected} on benchmark {index}.")],
        )
        correct += int(result.answerable and expected in result.answer)
        support += int(
            result.answerable
            and all(
                service._checker.supported(
                    claim.text,
                    result.citations,
                    claim.citation_ids,
                )
                for claim in result.claims
            )
        )
        severe_hallucinations += int(
            result.answerable and expected not in result.answer
        )
    for index in range(unanswerable_total):
        result = service.answer(
            "What was the energy consumption?",
            [hit(f"The paper reports accuracy {80 + index}% only.")],
        )
        refused += int(not result.answerable)

    assert correct / answerable_total >= 0.80
    assert support / answerable_total >= 0.90
    assert refused / unanswerable_total >= 0.85
    assert severe_hallucinations / answerable_total < 0.03
