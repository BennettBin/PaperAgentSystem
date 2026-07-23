from evaluation.section_resolver_evaluation import evaluate_section_resolver


def test_fixed_100_query_section_resolver_evaluation() -> None:
    metrics = evaluate_section_resolver()

    assert metrics.query_count == 100
    assert metrics.top1 >= 0.95
    assert metrics.number_exact == 1.0
    assert metrics.alias_top1 >= 0.95
    assert metrics.false_forced_match <= 0.02
    assert metrics.unresolved_rejection >= 0.98
    assert metrics.ambiguity_clarification >= 0.95


def test_fuzzy_threshold_is_calibrated_on_fixed_benchmark() -> None:
    selected = evaluate_section_resolver(fuzzy_threshold=0.92)
    stricter = evaluate_section_resolver(fuzzy_threshold=0.94)

    assert selected.fuzzy_top1 >= 0.95
    assert selected.false_forced_match <= 0.02
    assert selected.fuzzy_top1 > stricter.fuzzy_top1
