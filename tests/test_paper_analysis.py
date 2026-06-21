from academic_tasks.paper_analysis import EvidencePassage, PaperCardExtractor


def passages(index: int = 0) -> list[EvidencePassage]:
    values = {
        "title": f"Paper {index}",
        "research_question": f"Question {index}",
        "methodology": f"Method {index}",
        "datasets": f"Dataset {index}",
        "metrics": f"Accuracy {index}",
        "results": f"Result {80 + index % 20}%",
        "contributions": f"Contribution {index}",
        "limitations": f"Limitation {index}",
    }
    return [
        EvidencePassage(
            evidence_id=f"ev-{index}-{field}",
            text=f"{field}: {value}",
            page=position + 1,
            field_hint=field,
        )
        for position, (field, value) in enumerate(values.items())
    ]


def test_paper_card_fields_are_bound_to_evidence() -> None:
    card = PaperCardExtractor().extract(passages())

    assert card.title == "Paper 0"
    assert card.results == ["Result 80%"]
    assert card.missing_fields == []
    assert {evidence.field for evidence in card.evidence} == {
        "title",
        "research_question",
        "methodology",
        "datasets",
        "metrics",
        "results",
        "contributions",
        "limitations",
    }
    assert all(evidence.evidence_id.startswith("ev-0-") for evidence in card.evidence)


def test_missing_fields_are_explicit_and_not_invented() -> None:
    card = PaperCardExtractor().extract(passages()[:3])

    assert card.datasets == []
    assert "datasets" in card.missing_fields
    assert "results" in card.missing_fields


def test_paper_card_field_f1_threshold() -> None:
    extractor = PaperCardExtractor()
    tp = fp = fn = 0
    for index in range(100):
        expected = {
            "title": f"Paper {index}",
            "research_question": f"Question {index}",
            "methodology": f"Method {index}",
            "datasets": [f"Dataset {index}"],
            "metrics": [f"Accuracy {index}"],
            "results": [f"Result {80 + index % 20}%"],
            "contributions": [f"Contribution {index}"],
            "limitations": [f"Limitation {index}"],
        }
        card = extractor.extract(passages(index))
        actual = {
            field: getattr(card, field)
            for field in expected
        }
        tp += sum(actual[field] == value for field, value in expected.items())
        fp += sum(bool(actual[field]) and actual[field] != value for field, value in expected.items())
        fn += sum(not actual[field] or actual[field] != value for field, value in expected.items())

    precision = tp / (tp + fp)
    recall = tp / (tp + fn)
    f1 = 2 * precision * recall / (precision + recall)
    assert f1 >= 0.85
