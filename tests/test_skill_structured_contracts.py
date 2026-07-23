from pathlib import Path

import pytest

from backend.agent_runtime.skill_selector import SkillSelector
from backend.infrastructure.fake.observability import FakeTraceWriter
from backend.skills.loader import SkillManifestLoader, SkillRegistry
from backend.skills.runtime import SkillRuntime

ROOT = Path(__file__).resolve().parents[1]
REAL_TOOLS = {
    "parse_document",
    "search_document",
    "get_document_section",
    "extract_paper_card",
    "build_comparison_table",
    "build_literature_review",
    "save_artifact",
}


def _registry() -> tuple[SkillRegistry, FakeTraceWriter]:
    traces = FakeTraceWriter()
    registry = SkillRegistry(traces)
    registry.load_all(
        SkillManifestLoader(
            ROOT / "backend" / "skills",
            registered_tools=REAL_TOOLS,
            available_profiles={"development", "paper_reader_v1"},
        )
    )
    return registry, traces


def test_each_skill_declares_structured_contract_and_local_tool_bindings() -> None:
    registry, _ = _registry()

    for skill in registry.list_all():
        assert skill.input_contract.format in {"object", "markdown", "markdown_table"}
        assert skill.output_contract.format in {"object", "markdown", "markdown_table"}
        assert skill.tools
        assert (ROOT / "backend" / "skills" / skill.name / "tools" / "tools.yaml").is_file()
        for tool in skill.tools:
            assert tool.name in REAL_TOOLS
            assert tool.name in skill.instructions
            assert tool.purpose
            assert tool.when_to_use


@pytest.mark.asyncio
async def test_markdown_output_is_validated_without_json_envelope() -> None:
    registry, traces = _registry()
    runtime = SkillRuntime(
        SkillSelector(registry, fallback_skill="paper_reader"), registry
    )
    activation = await runtime.activate(
        "总结论文",
        {
            "request": "总结论文",
            "file_ids": ["file-1"],
            "conversation_id": "conversation-1",
            "parameters": {},
        },
        "trace-markdown",
    )

    output = await runtime.complete(
        activation,
        "## 摘要\n\n论文提出了一种证据化方法 [E1]。",
        "trace-markdown",
    )

    assert output.startswith("## 摘要")
    assert traces.traces[-1]["span_name"] == "skill.complete"
    with pytest.raises(ValueError, match="Skill output"):
        await runtime.complete(activation, {"answer": "not markdown"}, "trace-bad")


@pytest.mark.asyncio
async def test_skill_tool_arguments_are_checked_and_traced() -> None:
    registry, traces = _registry()
    runtime = SkillRuntime(
        SkillSelector(registry, fallback_skill="paper_reader"), registry
    )
    activation = await runtime.activate(
        "总结论文",
        {
            "request": "总结论文",
            "file_ids": ["file-1"],
            "conversation_id": "conversation-1",
            "parameters": {},
        },
        "trace-tool",
    )

    binding = await runtime.start_tool(
        activation,
        "search_document",
        {"query": "dataset", "file_ids": ["file-1"], "limit": 8},
        "trace-tool",
    )
    await runtime.complete_tool(binding, {"hits": []}, "trace-tool")

    assert traces.traces[-2]["span_name"] == "skill.tool.started"
    assert traces.traces[-2]["data"]["parameters_valid"] is True
    assert traces.traces[-1]["span_name"] == "skill.tool.completed"
    with pytest.raises(ValueError, match="Tool input"):
        await runtime.start_tool(
            activation,
            "search_document",
            {"query": "dataset", "file_ids": "file-1", "limit": 99},
            "trace-invalid-tool",
        )
    assert traces.traces[-1]["span_name"] == "skill.tool.rejected"
    assert traces.traces[-1]["data"]["parameters_valid"] is False
