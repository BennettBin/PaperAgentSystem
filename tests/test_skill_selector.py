import json
from pathlib import Path

import pytest

from backend.agent_runtime.skill_selector import (
    SkillSelectionContext,
    SkillSelector,
)
from backend.infrastructure.fake.observability import FakeTraceWriter
from backend.skills.loader import SkillManifestLoader, SkillRegistry

SKILLS_ROOT = Path(__file__).parents[1] / "backend" / "skills"


def selector() -> SkillSelector:
    registry = SkillRegistry(FakeTraceWriter())
    registry.load_all(
        SkillManifestLoader(
            SKILLS_ROOT,
            registered_tools={
                "parse_document", "get_document_section", "search_document",
                "build_comparison_table",
                "save_artifact",
                "build_literature_review", "extract_paper_card",
                "search_crossref", "search_semantic_scholar",
                "search_openalex", "search_arxiv",
            },
            available_profiles={"development", "paper_reader_v1"},
        )
    )
    return SkillSelector(registry, fallback_skill="paper_reader")


class ChoiceLLM:
    def __init__(self, selected: list[str], primary: str | None = None) -> None:
        self.selected = selected
        self.primary = primary

    async def generate_with_schema(self, _prompt: str, **_kwargs: object) -> str:
        return json.dumps(
            {
                "selected_skills": self.selected,
                "primary_skill": self.primary,
                "reason_summary": "公开的选择摘要",
            },
            ensure_ascii=False,
        )


class SemanticEmbedding:
    def __init__(self) -> None:
        self.batch_calls = 0

    async def embed(self, text: str) -> list[float]:
        return [1.0, 0.0] if "横向评估" in text else [0.0, 1.0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        self.batch_calls += 1
        return [
            [1.0, 0.0] if "comparison_analyzer" in text else [0.0, 1.0]
            for text in texts
        ]


@pytest.mark.asyncio
async def test_selector_returns_top_three_and_lazily_loads_only_selected_body() -> None:
    service = selector()

    result = await service.select("比较三篇论文的方法和实验")

    assert result.selected.name == "comparison_analyzer"
    assert len(result.candidates) == 3
    assert service.loaded_instruction_names == {"comparison_analyzer"}
    assert result.selected.instructions.startswith("---")
    assert "# 多论文对比" in result.selected.instructions


@pytest.mark.asyncio
async def test_selector_falls_back_for_unknown_intent() -> None:
    result = await selector().select("做一个完全未知但与论文有关的操作")

    assert result.selected.name == "paper_reader"
    assert result.used_fallback


@pytest.mark.asyncio
async def test_skill_selector_meets_top1_and_top3_thresholds() -> None:
    service = selector()
    labeled = [
        ("总结这篇论文", "summary_generator"),
        ("生成论文摘要", "summary_generator"),
        ("比较多篇论文", "comparison_analyzer"),
        ("对比方法和实验", "comparison_analyzer"),
        ("验证这个论断", "claim_verifier"),
        ("核验主张是否有证据", "claim_verifier"),
        ("提取论文主张", "claim_extractor"),
        ("抽取事实性结论", "claim_extractor"),
        ("分析研究局限", "limitation_analyst"),
        ("找出论文限制", "limitation_analyst"),
        ("审查研究方法", "methodology_reviewer"),
        ("评价实验方法", "methodology_reviewer"),
        ("整理参考文献", "citation_manager"),
        ("检查引用", "citation_manager"),
        ("解析 PDF 文档", "document_parser"),
        ("提取文档章节", "document_parser"),
        ("综合多篇文献", "literature_synthesizer"),
        ("写文献综述", "literature_synthesizer"),
        ("提炼新洞见", "insight_extractor"),
        ("发现证据支持的启示", "insight_extractor"),
        ("阅读单篇论文", "paper_reader"),
        ("生成 paper card", "paper_reader"),
    ] * 10
    top1 = 0
    top3 = 0
    for query, expected in labeled:
        result = await service.select(query)
        top1 += result.selected.name == expected
        top3 += expected in {item.name for item in result.candidates}

    assert top1 / len(labeled) >= 0.90
    assert top3 / len(labeled) >= 0.98


@pytest.mark.asyncio
async def test_hybrid_recall_caches_skill_vectors_and_hard_filters_file_count() -> None:
    service = selector()
    embeddings = SemanticEmbedding()
    service._embeddings = embeddings

    first = await service.select(
        "请做横向评估",
        SkillSelectionContext(file_count=2),
    )
    second = await service.select(
        "再次横向评估",
        SkillSelectionContext(file_count=1),
    )

    assert first.candidates[0].name == "comparison_analyzer"
    assert "comparison_analyzer" not in {item.name for item in second.candidates}
    assert embeddings.batch_calls == 1


@pytest.mark.asyncio
async def test_small_model_can_select_multiple_skills_and_planner_builds_dag() -> None:
    service = selector()
    service._decision_llm = ChoiceLLM(
        ["claim_extractor", "claim_verifier", "citation_manager"],
        "citation_manager",
    )

    result = await service.select("提取主张、验证主张并整理引用")

    assert {skill.name for skill in result.selected_skills} == {
        "claim_extractor",
        "claim_verifier",
        "citation_manager",
    }
    assert result.selected.name == "citation_manager"
    assert result.plan is not None
    steps = {step.skill_name: step for step in result.plan.steps}
    assert steps["claim_verifier"].depends_on == ("claim_extractor",)
    assert set(steps["citation_manager"].depends_on) == {
        "claim_extractor",
        "claim_verifier",
    }


@pytest.mark.asyncio
async def test_model_cannot_select_skill_outside_filtered_candidates() -> None:
    service = selector()
    service._decision_llm = ChoiceLLM(["comparison_analyzer"], "comparison_analyzer")

    result = await service.select(
        "总结论文",
        SkillSelectionContext(
            file_count=1,
            permitted_skills=frozenset({"summary_generator"}),
        ),
    )

    assert result.selected.name == "summary_generator"
    assert "确定性重规划" in result.reason_summary
