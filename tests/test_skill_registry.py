from pathlib import Path

import pytest

from infrastructure.fake.observability import FakeTraceWriter
from skills.loader import SkillManifestLoader, SkillRegistry

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
}


def loader(root: Path = ROOT / "skills") -> SkillManifestLoader:
    return SkillManifestLoader(
        root,
        registered_tools=TOOLS,
        available_profiles={"development", "paper_reader_v1"},
    )


@pytest.mark.asyncio
async def test_all_eleven_skills_are_complete_and_version_is_traced() -> None:
    traces = FakeTraceWriter()
    registry = SkillRegistry(traces)
    registry.load_all(loader())

    skills = registry.list_all()
    assert len(skills) == 11
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
    assert skill.examples[0]["output"]["status"]
    assert skill.allowed_tools
    assert "## Acceptance" in skill.instructions


def test_invalid_example_fails_explicitly(tmp_path: Path) -> None:
    skill = tmp_path / "bad"
    skill.mkdir()
    (skill / "manifest.yaml").write_text(
        "name: bad\nversion: 1.0.0\ndescription: bad\n"
        "model_profile: development\nallowed_tools: []\n"
        "output_schema: output.schema.json\n"
        "clarification_conditions: [missing]\n"
        "termination_conditions: [done]\n"
        "acceptance_rules: [valid]\n",
        encoding="utf-8",
    )
    (skill / "SKILL.md").write_text("# Bad", encoding="utf-8")
    (skill / "output.schema.json").write_text(
        '{"type":"object","required":["status"]}',
        encoding="utf-8",
    )
    (skill / "examples.json").write_text(
        '[{"input":{},"output":{"wrong":"value"}}]',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Schema validation failed"):
        loader(tmp_path).discover()


def test_missing_skill_file_fails_explicitly(tmp_path: Path) -> None:
    skill = tmp_path / "missing"
    skill.mkdir()
    (skill / "manifest.yaml").write_text("name: missing", encoding="utf-8")

    with pytest.raises(ValueError, match="Missing Skill files"):
        loader(tmp_path).discover()
