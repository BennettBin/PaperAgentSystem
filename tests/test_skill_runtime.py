import json
from pathlib import Path

import pytest

from backend.agent_runtime.skill_selector import SkillSelector
from backend.infrastructure.fake.observability import FakeTraceWriter
from backend.skills.loader import SkillManifestLoader, SkillRegistry
from backend.skills.runtime import SkillRuntime

ROOT = Path(__file__).resolve().parents[1]
TOOLS = {
    "parse_document", "get_document_section", "search_document",
    "build_comparison_table", "save_artifact",
    "build_literature_review", "extract_paper_card",
    "search_crossref", "search_semantic_scholar",
    "search_openalex", "search_arxiv",
}


def runtime() -> tuple[SkillRuntime, FakeTraceWriter]:
    traces = FakeTraceWriter()
    registry = SkillRegistry(traces)
    registry.load_all(SkillManifestLoader(
        ROOT / "backend" / "skills", registered_tools=TOOLS,
        available_profiles={"development", "paper_reader_v1"},
    ))
    return SkillRuntime(SkillSelector(registry, fallback_skill="paper_reader"), registry), traces


@pytest.mark.asyncio
async def test_runtime_selects_activates_and_validates_json_boundaries() -> None:
    service, traces = runtime()
    activation = await service.activate(
        "总结这篇论文",
        {"request": "总结这篇论文", "file_ids": ["file-1"], "conversation_id": "conversation-1", "parameters": {}},
        "trace-1",
    )
    assert activation.skill.name == "summary_generator"
    result = await service.complete(
        activation,
        "## 摘要\n\n论文摘要内容 [E1]。",
        "trace-1",
    )
    assert "论文摘要内容" in result
    assert [item["span_name"] for item in traces.traces[-2:]] == ["skill.activate", "skill.complete"]


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", ["not-an-object", {"request":"总结","file_ids":"file-1","conversation_id":"c","parameters":{}}])
async def test_runtime_rejects_invalid_skill_input(payload: object) -> None:
    service, traces = runtime()
    with pytest.raises(ValueError, match="Skill input"):
        await service.activate("总结论文", payload, "trace-invalid")
    assert traces.traces == []


@pytest.mark.asyncio
async def test_runtime_rejects_invalid_skill_output_json() -> None:
    service, _ = runtime()
    activation = await service.activate("阅读论文", {"request":"阅读论文","file_ids":["file-1"],"conversation_id":"c","parameters":{}}, "trace-output")
    with pytest.raises(ValueError, match="Skill output"):
        await service.complete(activation, {"status":"completed"}, "trace-output")


@pytest.mark.asyncio
async def test_runtime_activates_and_completes_a_multi_skill_plan() -> None:
    service, traces = runtime()

    class MultiChoiceLLM:
        async def generate_with_schema(self, _prompt: str, **_kwargs: object) -> str:
            return json.dumps(
                {
                    "selected_skills": ["summary_generator", "limitation_analyst"],
                    "primary_skill": "summary_generator",
                    "reason_summary": "同时总结并分析局限",
                },
                ensure_ascii=False,
            )

    service._selector._decision_llm = MultiChoiceLLM()
    activation = await service.activate(
        "总结论文并分析研究局限",
        {"request":"总结并分析局限","file_ids":["file-1"],"conversation_id":"c","parameters":{}},
        "trace-multi",
    )
    await service.complete(
        activation,
        "## 摘要与局限\n\n论文结论及其局限均有证据支持 [E1]。",
        "trace-multi",
    )

    assert {skill.name for skill in activation.skills} == {
        "summary_generator",
        "limitation_analyst",
    }
    assert [item["span_name"] for item in traces.traces].count("skill.activate") == 2
    assert [item["span_name"] for item in traces.traces].count("skill.complete") == 2
