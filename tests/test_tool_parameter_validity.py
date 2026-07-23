from evaluation.tool_parameter_validity import calculate_tool_parameter_validity


def test_tool_parameter_validity_has_explicit_numerator_and_denominator() -> None:
    metric = calculate_tool_parameter_validity(
        [
            {"span_name": "skill.tool.started", "data": {"parameters_valid": True}},
            {"span_name": "skill.tool.rejected", "data": {"parameters_valid": False}},
            {"span_name": "other", "data": {}},
        ]
    )

    assert metric.valid_calls == 1
    assert metric.total_calls == 2
    assert metric.rate == 0.5


def test_tool_parameter_validity_is_undefined_without_calls() -> None:
    metric = calculate_tool_parameter_validity([])

    assert metric.total_calls == 0
    assert metric.rate is None
