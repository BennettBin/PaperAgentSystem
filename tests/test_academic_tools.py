import pytest

from academic_tasks.paper_analysis import EvidencePassage
from academic_tasks.writing_brief import StatementKind
from infrastructure.fake.observability import FakeTraceWriter
from tool_runtime import (
    InMemoryDataRefStore,
    InMemoryIdempotencyStore,
    ToolContext,
    ToolRegistry,
    ToolRuntime,
)
from tool_runtime.academic_tools import register_academic_tools


@pytest.mark.asyncio
async def test_academic_tools_are_callable_only_through_registry() -> None:
    registry = ToolRegistry()
    register_academic_tools(registry)
    runtime = ToolRuntime(
        registry,
        idempotency_store=InMemoryIdempotencyStore(),
        data_ref_store=InMemoryDataRefStore(),
        trace_writer=FakeTraceWriter(),
        max_inline_bytes=100_000,
    )
    allowed = {tool.name for tool in registry.list_all()}
    context = ToolContext(
        workspace_id="ws",
        user_id="user",
        conversation_id="conv",
        task_id="task",
        trace_id="trace",
        permissions=frozenset({"workspace:read", "workspace:write"}),
        allowed_tools=frozenset(allowed),
    )

    card = await runtime.invoke(
        "extract_paper_card",
        {
            "passages": [
                EvidencePassage(
                    evidence_id="E1",
                    text="title: Evidence Paper",
                    page=1,
                    field_hint="title",
                )
            ]
        },
        context,
        "academic-card",
    )

    assert card.output["card"]["title"] == "Evidence Paper"
    assert card.output["card"]["missing_fields"]

    card_payload = {
        "title": "Paper",
        "research_question": "RQ",
        "methodology": "Method",
        "datasets": ["Dataset"],
        "metrics": ["Accuracy"],
        "results": ["Accuracy 95%"],
        "contributions": ["Contribution"],
        "limitations": ["Limitation"],
        "evidence": [
            {
                "evidence_id": "E-results",
                "field": "results",
                "quote": "Accuracy 95%",
                "page": 1,
            }
        ],
        "missing_fields": [],
    }
    compared = await runtime.invoke(
        "build_comparison_table",
        {
            "papers": [
                {"file_id": "file-1", "card": card_payload},
                {"file_id": "file-2", "card": card_payload},
            ],
            "dimensions": ["results"],
        },
        context,
        "academic-compare",
    )
    brief = await runtime.invoke(
        "build_writing_brief",
        {
            "section_type": "results",
            "target_language": "zh",
            "target_length": 500,
            "style": "academic",
            "user_points": ["报告准确率"],
            "materials": [
                {
                    "source_id": "source-1",
                    "text": "Accuracy is 95%.",
                    "kind": StatementKind.FACT.value,
                    "evidence_ids": ["E-results"],
                }
            ],
            "immutable_items": ["95%"],
        },
        context,
        "academic-brief",
    )
    drafted = await runtime.invoke(
        "draft_paper_section",
        {"brief": brief.output},
        context,
        "academic-draft",
    )
    rewritten = await runtime.invoke(
        "rewrite_academic_text",
        {
            "text": "Model-X achieved 95% [C1].",
            "mode": "polish",
            "protected_terms": ["Model-X"],
        },
        context,
        "academic-rewrite",
    )
    reviewed = await runtime.invoke(
        "build_literature_review",
        {
            "evidence_map": brief.output["evidence_map"],
            "themes": {"results": ["statement-1"]},
            "inferences": ["The effect may depend on the dataset."],
        },
        context,
        "academic-review",
    )

    assert compared.output["conclusions"][0]["evidence_ids"]
    assert drafted.output["review_required"] is True
    assert rewritten.output["regression_passed"] is True
    assert reviewed.output["verification_errors"] == []
