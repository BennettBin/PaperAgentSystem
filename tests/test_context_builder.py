from agent_runtime.context_builder import ContextBuilder, ContextInput, ContextSource


def test_context_contains_required_sections_and_traceable_sources() -> None:
    result = ContextBuilder().build(
        ContextInput(
            system_policy="Never invent facts.",
            requirement_brief="Summarize paper.pdf.",
            skill_instructions="Use cited evidence.",
            tool_schemas='{"search": {}}',
            plan="1. search 2. summarize",
            recent_messages=["user: summarize"],
            memory=[ContextSource("memory:m1", "output Chinese")],
            workspace=[ContextSource("workspace:f1", "paper.pdf")],
            rag_evidence=[ContextSource("chunk:c1", "supported result")],
        ),
        context_length=4096,
        reserved_output_tokens=512,
    )

    assert "Never invent facts." in result.text
    assert "[source:memory:m1]" in result.text
    assert "[source:workspace:f1]" in result.text
    assert "[source:chunk:c1]" in result.text
    assert result.source_ids == {"memory:m1", "workspace:f1", "chunk:c1"}


def test_context_truncates_low_priority_content_within_profile_limit() -> None:
    long_text = "evidence " * 1000
    result = ContextBuilder().build(
        ContextInput(
            system_policy="policy",
            requirement_brief="brief",
            skill_instructions="skill",
            tool_schemas="schemas",
            plan="plan",
            recent_messages=["recent"],
            memory=[ContextSource("m1", long_text)],
            workspace=[ContextSource("w1", long_text)],
            rag_evidence=[ContextSource("r1", long_text)],
        ),
        context_length=300,
        reserved_output_tokens=100,
    )

    assert result.estimated_tokens <= 200
    assert "policy" in result.text
    assert "brief" in result.text
    assert result.truncated


def test_context_rejects_untraceable_retrieval_content() -> None:
    try:
        ContextSource("", "content")
    except ValueError as exc:
        assert "source_id" in str(exc)
    else:
        raise AssertionError("empty source_id should be rejected")
