import json
from pathlib import Path

import pytest

from backend.agent_runtime.skill_preflight import (
    SkillInputSnapshot,
    SkillPreflight,
)
from backend.agent_runtime.skill_selector import (
    SkillSelectionContext,
    SkillSelector,
)
from backend.agent_runtime.structured_requirement import (
    MemoryMode,
    SourceMode,
    TaskType,
    TurnRelation,
)
from backend.infrastructure.fake.observability import FakeTraceWriter
from backend.skills.loader import SkillManifestLoader, SkillRegistry

SKILLS_ROOT = Path(__file__).parents[1] / "backend" / "skills"


class StructuredChoiceLLM:
    async def generate_with_schema(self, _prompt: str, **_kwargs: object) -> str:
        return json.dumps(
            {
                "task_type": "academic_rewrite",
                "turn_relation": "new_task",
                "source_mode": "inline_text",
                "memory_mode": "none",
                "selected_skills": ["academic_rewriter"],
                "primary_skill": "academic_rewriter",
                "needs_clarification": False,
                "clarification_questions": [],
                "missing_inputs": [],
                "confidence": 0.96,
                "reason_summary": "用户提供了正文并明确要求润色",
            },
            ensure_ascii=False,
        )


def _registry() -> SkillRegistry:
    registry = SkillRegistry(FakeTraceWriter())
    registry.load_all(
        SkillManifestLoader(
            SKILLS_ROOT,
            registered_tools={
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
            },
            available_profiles={"development", "paper_reader_v1"},
        )
    )
    return registry


@pytest.mark.asyncio
async def test_small_model_returns_requirement_and_skill_in_one_call() -> None:
    selector = SkillSelector(
        _registry(),
        fallback_skill="paper_reader",
        decision_llm=StructuredChoiceLLM(),
        top_k=5,
    )

    result = await selector.select(
        "请润色下面这段论文文字：业务流程运行具有高度动态性。",
        SkillSelectionContext(has_inline_text=True),
    )

    assert result.selected.name == "academic_rewriter"
    assert result.requirement.task_type is TaskType.ACADEMIC_REWRITE
    assert result.requirement.turn_relation is TurnRelation.NEW_TASK
    assert result.requirement.source_mode is SourceMode.INLINE_TEXT
    assert result.requirement.memory_mode is MemoryMode.NONE


@pytest.mark.asyncio
async def test_missing_file_does_not_remove_suitable_skill_before_preflight() -> None:
    selector = SkillSelector(_registry(), fallback_skill="paper_reader", top_k=5)

    selection = await selector.select(
        "总结这篇论文",
        SkillSelectionContext(file_count=0),
    )

    assert "summary_generator" in {item.name for item in selection.candidates}
    result = SkillPreflight().check(
        selection.selected,
        selection.requirement,
        SkillInputSnapshot(file_count=0, has_inline_text=False, has_conversation_material=False),
    )
    assert not result.ready
    assert result.clarification_questions


def test_academic_rewriter_accepts_inline_and_historical_material() -> None:
    skill = _registry().get("academic_rewriter")
    assert skill is not None
    assert skill.input_policy.source_required
    assert set(skill.input_policy.accepted_sources) >= {
        "inline_text",
        "conversation_material",
        "uploaded_files",
    }
