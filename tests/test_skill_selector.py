from pathlib import Path

import pytest

from agent_runtime.skill_selector import SkillSelector

SKILLS_ROOT = Path(__file__).parents[1] / "skills"


def selector() -> SkillSelector:
    return SkillSelector(SKILLS_ROOT, fallback_skill="paper_reader")


@pytest.mark.asyncio
async def test_selector_returns_top_three_and_lazily_loads_only_selected_body() -> None:
    service = selector()

    result = await service.select("比较三篇论文的方法和实验")

    assert result.selected.name == "comparison_analyzer"
    assert len(result.candidates) == 3
    assert service.loaded_instruction_names == {"comparison_analyzer"}
    assert result.selected.instructions.startswith("#")


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
