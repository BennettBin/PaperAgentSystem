from pathlib import Path

import pytest

from skills.loader import SkillManifestLoader

ROOT = Path(__file__).resolve().parents[1]
TOOLS = {
    "parse_document",
    "get_document_section",
    "search_document",
    "verify_claim",
    "verify_citations",
    "build_comparison_table",
    "save_artifact",
}


def test_all_eleven_skill_manifests_load():
    loader = SkillManifestLoader(
        ROOT / "skills",
        registered_tools=TOOLS,
        available_profiles={"development", "paper_reader_v1"},
    )
    loaded = loader.discover()

    assert len(loaded) == 11
    assert len({skill.name for skill in loaded}) == 11
    assert all(skill.output_schema["type"] == "object" for skill in loaded)
    assert all(
        "/" not in skill.model_profile and "\\" not in skill.model_profile for skill in loaded
    )


def test_unregistered_tool_is_rejected(tmp_path):
    skill_dir = tmp_path / "bad"
    skill_dir.mkdir()
    (skill_dir / "manifest.yaml").write_text(
        "name: bad\nversion: 1.0.0\ndescription: bad\n"
        "model_profile: development\nallowed_tools: [missing]\n"
        "output_schema: output.schema.json\n"
        "clarification_conditions: [missing input]\n"
        "termination_conditions: [done]\n"
        "acceptance_rules: [valid output]\n",
        encoding="utf-8",
    )
    (skill_dir / "SKILL.md").write_text("# Bad", encoding="utf-8")
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
        "model_profile: unavailable\nallowed_tools: []\n"
        "output_schema: output.schema.json\n"
        "clarification_conditions: [missing input]\n"
        "termination_conditions: [done]\n"
        "acceptance_rules: [valid output]\n",
        encoding="utf-8",
    )
    (skill_dir / "SKILL.md").write_text("# Fallback", encoding="utf-8")
    (skill_dir / "output.schema.json").write_text('{"type":"object"}', encoding="utf-8")
    (skill_dir / "examples.json").write_text(
        '[{"input":{},"output":{}}]',
        encoding="utf-8",
    )
    loader = SkillManifestLoader(tmp_path, set(), {"development"})

    assert loader.discover()[0].model_profile == "development"


def test_paper_reader_agent_has_single_file_scope():
    text = (ROOT / "subagents" / "paper_reader_agent.yaml").read_text("utf-8")
    assert "file_scope: single_file" in text
    assert "max_depth: 1" in text
