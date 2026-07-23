from backend.rag.section_resolver import (
    SectionContext,
    SectionRecord,
    SectionReferenceParser,
    SectionResolver,
)


def section(
    section_id: str,
    number: str | None,
    title: str,
    *,
    file_id: str = "paper-1",
    ordinal: int = 0,
) -> SectionRecord:
    return SectionRecord(
        section_id=section_id,
        document_id="document-1",
        file_id=file_id,
        number=number,
        title=title,
        normalized_title="",
        section_path=[title],
        parent_section_id=None,
        ordinal=ordinal,
    )


def test_resolver_uses_exact_number_before_title_similarity() -> None:
    resolver = SectionResolver()
    parser = SectionReferenceParser()
    sections = [
        section("methods", "2", "Methods"),
        section("architecture", "3.2", "Model Architecture"),
        section("similar", "4.2", "Architecture Evaluation"),
    ]

    result = resolver.resolve(parser.parse("解释 section 3.2"), sections)

    assert result.status == "resolved"
    assert result.selected is not None
    assert result.selected.section_id == "architecture"
    assert result.match_kind == "number_exact"


def test_resolver_handles_normalized_titles_and_versioned_aliases() -> None:
    resolver = SectionResolver()
    parser = SectionReferenceParser()
    sections = [
        section("methods", "2", "Materials and Methods"),
        section("results", "4", "Results and Findings"),
    ]

    methods = resolver.resolve(parser.parse("方法部分用了什么数据？"), sections)
    results = resolver.resolve(parser.parse("findings section"), sections)

    assert methods.selected is not None
    assert methods.selected.section_id == "methods"
    assert methods.match_kind == "alias_exact"
    assert results.selected is not None
    assert results.selected.section_id == "results"
    assert resolver.alias_version == "section-aliases-v1"


def test_resolver_accepts_safe_fuzzy_match_but_rejects_unrelated_title() -> None:
    resolver = SectionResolver()
    parser = SectionReferenceParser()
    sections = [
        section("architecture", "3.2", "Model Architecture"),
        section("experiments", "4", "Experimental Setup"),
    ]

    fuzzy = resolver.resolve(parser.parse("model archtecture section"), sections)
    missing = resolver.resolve(parser.parse("Ethical Deployment section"), sections)

    assert fuzzy.status == "resolved"
    assert fuzzy.selected is not None
    assert fuzzy.selected.section_id == "architecture"
    assert fuzzy.match_kind == "title_fuzzy"
    assert missing.status == "unresolved"
    assert missing.selected is None
    assert missing.candidates


def test_resolver_returns_ambiguity_instead_of_arbitrary_choice() -> None:
    resolver = SectionResolver()
    parser = SectionReferenceParser()
    sections = [
        section("analysis-method", "2.3", "Analysis", ordinal=2),
        section("analysis-result", "4.2", "Analysis", ordinal=8),
    ]

    result = resolver.resolve(parser.parse("总结 Analysis section"), sections)

    assert result.status == "ambiguous"
    assert result.selected is None
    assert {candidate.section.section_id for candidate in result.candidates} == {
        "analysis-method",
        "analysis-result",
    }
    assert result.clarification_question


def test_deictic_resolution_requires_context_and_supports_previous_section() -> None:
    resolver = SectionResolver()
    parser = SectionReferenceParser()
    sections = [
        section("methods", "2", "Methods", ordinal=1),
        section("results", "3", "Results", ordinal=2),
    ]

    missing = resolver.resolve(parser.parse("总结这一节"), sections)
    current = resolver.resolve(
        parser.parse("总结这一节"),
        sections,
        context=SectionContext(current_section_id="results"),
    )
    previous = resolver.resolve(
        parser.parse("上一节讲了什么"),
        sections,
        context=SectionContext(current_section_id="results"),
    )

    assert missing.status == "unresolved"
    assert missing.reason == "missing_section_context"
    assert current.selected is not None
    assert current.selected.section_id == "results"
    assert previous.selected is not None
    assert previous.selected.section_id == "methods"


def test_duplicate_number_across_files_is_ambiguous_without_file_scope() -> None:
    resolver = SectionResolver()
    parser = SectionReferenceParser()
    sections = [
        section("paper-1-methods", "2", "Methods", file_id="paper-1"),
        section("paper-2-methods", "2", "Methodology", file_id="paper-2"),
    ]

    result = resolver.resolve(parser.parse("解释第 2 节"), sections)

    assert result.status == "ambiguous"
    assert len(result.candidates) == 2


def test_reliable_missing_number_does_not_fall_back_to_matching_title() -> None:
    resolver = SectionResolver()
    parser = SectionReferenceParser()
    sections = [section("results", "5", "Results")]

    result = resolver.resolve(
        parser.parse("解释 section 9.9 Results"),
        sections,
    )

    assert result.status == "unresolved"
    assert result.reason == "section_number_not_found"
    assert result.selected is None
