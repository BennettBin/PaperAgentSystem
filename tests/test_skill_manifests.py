from pathlib import Path

import pytest

from backend.skills.loader import SkillManifestLoader

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


def test_all_thirteen_skill_manifests_load():
    loader = SkillManifestLoader(
        ROOT / "backend" / "skills",
        registered_tools=TOOLS,
        available_profiles={"development", "paper_reader_v1"},
    )
    loaded = loader.discover()

    assert len(loaded) == 13
    assert len({skill.name for skill in loaded}) == 13
    assert all(skill.input_contract.format == "object" for skill in loaded)
    assert {skill.output_contract.format for skill in loaded} == {
        "object", "markdown", "markdown_table"
    }
    assert all(
        "/" not in skill.model_profile and "\\" not in skill.model_profile for skill in loaded
    )


def test_unregistered_tool_is_rejected(tmp_path):
    skill_dir = tmp_path / "bad"
    skill_dir.mkdir()
    (skill_dir / "manifest.yaml").write_text(
        "name: bad\nversion: 1.0.0\ndescription: bad\n"
        "model_profile: development\n"
        "input_contract: {format: object, schema: input.schema.json}\n"
        "output_contract: {format: object, schema: output.schema.json}\n"
        "trigger_conditions: [bad request]\nnon_trigger_conditions: [unrelated request]\n"
        "routing_keywords: [bad]\n"
        "clarification_conditions: [missing input]\n"
        "termination_conditions: [done]\n"
        "acceptance_rules: [valid output]\n",
        encoding="utf-8",
    )
    (skill_dir / "SKILL.md").write_text("# Bad", encoding="utf-8")
    (skill_dir / "tools").mkdir()
    (skill_dir / "tools" / "tools.yaml").write_text(
        "tools:\n  - name: missing\n    purpose: bad\n"
        "    when_to_use: bad\n"
        "    implementation: backend.tool_runtime.document_tools.SearchDocumentTool\n"
        "    example_input: {}\n",
        encoding="utf-8",
    )
    (skill_dir / "input.schema.json").write_text('{"type":"object"}', encoding="utf-8")
    (skill_dir / "output.schema.json").write_text('{"type":"object"}', encoding="utf-8")
    (skill_dir / "examples.json").write_text(
        '[{"input":{},"output":{}}]',
        encoding="utf-8",
    )
    loader = SkillManifestLoader(tmp_path, set(), {"development"})

    with pytest.raises(ValueError, match="Unregistered tools"):
        loader.discover()


def test_missing_profile_uses_logical_fallback(tmp_path):
    skill_dir = tmp_path / "fallback"
    skill_dir.mkdir()
    (skill_dir / "manifest.yaml").write_text(
        "name: fallback\nversion: 1.0.0\ndescription: fallback\n"
        "model_profile: unavailable\n"
        "input_contract: {format: object, schema: input.schema.json}\n"
        "output_contract: {format: object, schema: output.schema.json}\n"
        "trigger_conditions: [fallback request]\nnon_trigger_conditions: [unrelated request]\n"
        "routing_keywords: [fallback]\n"
        "clarification_conditions: [missing input]\n"
        "termination_conditions: [done]\n"
        "acceptance_rules: [valid output]\n",
        encoding="utf-8",
    )
    (skill_dir / "SKILL.md").write_text("# Fallback", encoding="utf-8")
    (skill_dir / "tools").mkdir()
    (skill_dir / "tools" / "tools.yaml").write_text(
        "tools:\n  - name: search_document\n    purpose: fallback\n"
        "    when_to_use: fallback\n"
        "    implementation: backend.tool_runtime.document_tools.SearchDocumentTool\n"
        "    example_input: {query: test, file_ids: [file-1], limit: 8}\n",
        encoding="utf-8",
    )
    (skill_dir / "input.schema.json").write_text('{"type":"object"}', encoding="utf-8")
    (skill_dir / "output.schema.json").write_text('{"type":"object"}', encoding="utf-8")
    (skill_dir / "examples.json").write_text(
        '[{"input":{},"output":{}}]',
        encoding="utf-8",
    )
    loader = SkillManifestLoader(tmp_path, {"search_document"}, {"development"})

    assert loader.discover()[0].model_profile == "development"


def test_paper_reader_agent_has_single_file_scope():
    text = (ROOT / "backend" / "subagents" / "paper_reader_agent.yaml").read_text("utf-8")
    assert "file_scope: single_file" in text
    assert "max_depth: 1" in text
