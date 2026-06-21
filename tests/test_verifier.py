from agent_runtime.verifier import (
    Claim,
    VerificationInput,
    VerificationStatus,
    Verifier,
)


def test_verifier_detects_unsupported_severe_claim_without_model() -> None:
    result = Verifier().verify(
        VerificationInput(
            output={"summary": "该方法彻底解决了所有安全问题。"},
            required_fields={"summary"},
            claims=[Claim("该方法彻底解决了所有安全问题。", severity="severe")],
        )
    )

    assert result.status is VerificationStatus.NEEDS_REPAIR
    assert any(issue.code == "unsupported_severe_claim" for issue in result.issues)
    assert result.repair_suggestion


def test_verifier_checks_schema_numbers_citations_and_invariants() -> None:
    result = Verifier().verify(
        VerificationInput(
            output={"text": "准确率为 95%，见 [C2]。术语 Beta。"},
            required_fields={"text", "sources"},
            claims=[Claim("准确率为 95%", evidence_ids=("C1",))],
            valid_citation_ids={"C1"},
            immutable_terms={"Alpha"},
            source_text="准确率为 90%，术语 Alpha。",
        )
    )

    codes = {issue.code for issue in result.issues}
    assert {"schema_missing", "number_mismatch", "invalid_citation", "invariant_missing"} <= codes


def test_verifier_passes_supported_output() -> None:
    result = Verifier().verify(
        VerificationInput(
            output={"text": "术语 Alpha，准确率为 90% [C1]", "sources": ["C1"]},
            required_fields={"text", "sources"},
            claims=[Claim("准确率为 90%", evidence_ids=("C1",))],
            valid_citation_ids={"C1"},
            immutable_terms={"Alpha"},
            source_text="准确率为 90%，术语 Alpha。",
        )
    )

    assert result.status is VerificationStatus.PASSED
    assert result.issues == []


def test_verifier_allows_at_most_two_repairs() -> None:
    verifier = Verifier()
    item = VerificationInput(
        output={"text": "无证据的重大结论"},
        required_fields={"text"},
        claims=[Claim("无证据的重大结论", severity="severe")],
    )

    first = verifier.verify(item, repair_count=0)
    second = verifier.verify(item, repair_count=1)
    final = verifier.verify(item, repair_count=2)

    assert first.status is VerificationStatus.NEEDS_REPAIR
    assert second.status is VerificationStatus.NEEDS_REPAIR
    assert final.status is VerificationStatus.FAILED
    assert final.repair_suggestion == ""
