from pathlib import Path

import pytest

from backend.infrastructure.fake.observability import FakeTraceWriter
from backend.skills.loader import SkillManifestLoader, SkillRegistry

ROOT = Path(__file__).resolve().parents[1]
TOOLS = {
    "parse_document",
    "get_document_section",
    "search_document",
    "build_comparison_table",
    "save_artifact",
    "build_literature_review",
    "extract_paper_card",
    "search_crossref",
    "search_semantic_scholar",
    "search_openalex",
    "search_arxiv",
}
SKILL_NAMES = {
    "paper_reader",
    "document_parser",
    "claim_extractor",
    "claim_verifier",
    "citation_manager",
    "summary_generator",
    "insight_extractor",
    "comparison_analyzer",
    "literature_synthesizer",
    "methodology_reviewer",
    "limitation_analyst",
    "paper_discovery",
    "academic_rewriter",
}


def loader(root: Path = ROOT / "backend" / "skills") -> SkillManifestLoader:
    return SkillManifestLoader(
        root,
        registered_tools=TOOLS,
        available_profiles={"development", "paper_reader_v1"},
    )


@pytest.mark.asyncio
async def test_all_thirteen_skills_are_complete_and_version_is_traced() -> None:
    traces = FakeTraceWriter()
    registry = SkillRegistry(traces)
    registry.load_all(loader())

    skills = registry.list_all()
    assert len(skills) == 13
    assert all(skill.input_contract for skill in skills)
    assert all(skill.output_contract for skill in skills)
    assert all(skill.trigger_conditions for skill in skills)
    assert all(skill.non_trigger_conditions for skill in skills)
    assert all(skill.examples for skill in skills)
    assert all(skill.clarification_conditions for skill in skills)
    assert all(skill.termination_conditions for skill in skills)
    assert all(skill.acceptance_rules for skill in skills)

    selected = await registry.activate("paper_reader", "trace-skill")

    assert selected.version == "1.0.0"
    assert traces.traces[-1]["data"]["skill_version"] == "1.0.0"
    assert traces.traces[-1]["data"]["model_profile"] == "paper_reader_v1"


@pytest.mark.parametrize("skill_name", sorted(SKILL_NAMES))
def test_each_skill_has_a_valid_example_and_runtime_contract(skill_name: str) -> None:
    registry = SkillRegistry(FakeTraceWriter())
    registry.load_all(loader())

    skill = registry.get(skill_name)

    assert skill is not None
    assert skill.examples[0]["input"] is not None
    assert skill.examples[0]["output"]
    assert skill.allowed_tools
    assert skill.input_contract.format == "object"
    assert "## Structured Input" in skill.instructions
    assert "## Structured Output" in skill.instructions
    assert "## Execution Steps" in skill.instructions
    assert "## Anti-Patterns" in skill.instructions
    assert "## Acceptance" in skill.instructions


def test_invalid_example_fails_explicitly(tmp_path: Path) -> None:
    skill = tmp_path / "bad"
    skill.mkdir()
    (skill / "manifest.yaml").write_text(
        "name: bad\nversion: 1.0.0\ndescription: bad\n"
        "model_profile: development\n"
        "input_contract: {format: object, schema: input.schema.json}\n"
        "output_contract: {format: object, schema: output.schema.json}\n"
        "trigger_conditions: [bad request]\n"
        "non_trigger_conditions: [unrelated request]\n"
        "routing_keywords: [bad]\n"
        "clarification_conditions: [missing]\n"
        "termination_conditions: [done]\n"
        "acceptance_rules: [valid]\n",
        encoding="utf-8",
    )
    (skill / "SKILL.md").write_text("# Bad", encoding="utf-8")
    (skill / "tools").mkdir()
    (skill / "tools" / "tools.yaml").write_text(
        "tools:\n  - name: search_document\n    purpose: test\n"
        "    when_to_use: test\n"
        "    implementation: backend.tool_runtime.document_tools.SearchDocumentTool\n"
        "    example_input: {query: test, file_ids: [file-1], limit: 8}\n",
        encoding="utf-8",
    )
    (skill / "input.schema.json").write_text('{"type":"object"}', encoding="utf-8")
    (skill / "output.schema.json").write_text(
        '{"type":"object","required":["status"]}', encoding="utf-8"
    )
    (skill / "examples.json").write_text(
        '[{"input":{},"output":{"wrong":"value"}}]', encoding="utf-8"
    )

    with pytest.raises(ValueError, match="Schema validation failed"):
        loader(tmp_path).discover()


def test_missing_skill_file_fails_explicitly(tmp_path: Path) -> None:
    skill = tmp_path / "missing"
    skill.mkdir()
    (skill / "manifest.yaml").write_text("name: missing", encoding="utf-8")

    with pytest.raises(ValueError, match="Missing Skill files"):
        loader(tmp_path).discover()
