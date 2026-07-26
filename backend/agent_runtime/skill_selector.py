"""Hybrid, bounded Skill selection with deterministic safety fallbacks."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.agent_runtime.skill_planner import (
    DeterministicSkillPlanner,
    SkillExecutionPlan,
    SkillPlanBudget,
)
from backend.agent_runtime.structured_requirement import (
    MemoryMode,
    SourceMode,
    StructuredRequirement,
    TaskType,
    TurnRelation,
    infer_structured_requirement,
)
from backend.core.errors import ProjectError
from backend.core.ports.llm_client import EmbeddingClient, LLMClient
from backend.skills.loader import LoadedSkill, SkillRegistry


@dataclass(frozen=True, slots=True)
class SkillSelectionContext:
    file_count: int | None = None
    permitted_skills: frozenset[str] | None = None
    permitted_tools: frozenset[str] | None = None
    budget: SkillPlanBudget = SkillPlanBudget()
    has_inline_text: bool = False
    has_conversation_material: bool = False
    pending_clarification: bool = False
    previous_request: str = ""


@dataclass(frozen=True, slots=True)
class SkillCandidate:
    name: str
    description: str
    score: float
    rule_score: float = 0.0
    semantic_score: float = 0.0


@dataclass(frozen=True, slots=True)
class SkillSelection:
    selected: LoadedSkill
    candidates: tuple[SkillCandidate, ...]
    used_fallback: bool
    selected_skills: tuple[LoadedSkill, ...] = ()
    plan: SkillExecutionPlan | None = None
    reason_summary: str = ""
    model_used: bool = False
    requirement: StructuredRequirement = StructuredRequirement(
        task_type=TaskType.DOCUMENT_QA
    )


class _ModelSkillChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selected_skills: list[str] = Field(default_factory=list, max_length=3)
    primary_skill: str | None = None
    reason_summary: str = Field(default="", max_length=240)
    task_type: TaskType | None = None
    turn_relation: TurnRelation = TurnRelation.NEW_TASK
    source_mode: SourceMode = SourceMode.NONE
    memory_mode: MemoryMode = MemoryMode.NONE
    needs_clarification: bool = False
    clarification_questions: list[str] = Field(default_factory=list, max_length=5)
    missing_inputs: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class SkillSelector:
    def __init__(
        self,
        registry: SkillRegistry,
        *,
        fallback_skill: str,
        decision_llm: LLMClient | None = None,
        embeddings: EmbeddingClient | None = None,
        top_k: int = 3,
    ) -> None:
        self._registry = registry
        self._fallback = fallback_skill
        self._decision_llm = decision_llm
        self._embeddings = embeddings
        self._top_k = max(1, top_k)
        self._candidate_vectors: dict[str, list[float]] | None = None
        self._planner = DeterministicSkillPlanner(registry)
        self.loaded_instruction_names: set[str] = set()

    async def select(
        self,
        requirement: str,
        context: SkillSelectionContext | None = None,
    ) -> SkillSelection:
        selection_context = context or SkillSelectionContext()
        eligible = self._hard_filter(requirement, selection_context)
        ranked = await self._hybrid_rank(requirement, eligible)
        candidates = tuple(ranked[: self._top_k])
        names, primary, reason, model_failed, model_choice = await self._model_select(
            requirement, candidates, selection_context
        )
        model_used = self._decision_llm is not None and bool(candidates)
        used_fallback = False
        if model_failed:
            names = [candidates[0].name] if candidates and candidates[0].score > 0 else []
            primary = names[0] if names else None
            reason = "小模型选择不可用，使用确定性候选结果"
        if not names:
            names = [self._fallback]
            primary = self._fallback
            used_fallback = True
            reason = reason or "没有匹配的专用 Skill，使用安全基线"

        candidate_names = {candidate.name for candidate in candidates}
        if not used_fallback and any(name not in candidate_names for name in names):
            names = [candidates[0].name] if candidates else [self._fallback]
            primary = names[0]
            used_fallback = not candidates
            reason = "小模型返回候选集外 Skill，已执行确定性重规划"

        try:
            plan = self._planner.create(
                names,
                primary_skill=primary,
                permitted_skills=selection_context.permitted_skills,
                permitted_tools=selection_context.permitted_tools,
                budget=selection_context.budget,
            )
        except ProjectError:
            fallback_name = candidates[0].name if candidates else self._fallback
            plan = self._planner.create(
                [fallback_name],
                primary_skill=fallback_name,
                permitted_skills=selection_context.permitted_skills,
                permitted_tools=selection_context.permitted_tools,
                budget=selection_context.budget,
                replan_count=1,
            )
            used_fallback = fallback_name == self._fallback
            reason = "Skill DAG、权限或预算校验失败，已执行一次确定性重规划"

        ordered = plan.topological_order()
        selected_skills = tuple(self._load_selected(name) for name in ordered)
        primary_skill = next(skill for skill in selected_skills if skill.name == plan.primary_skill)
        structured = infer_structured_requirement(
            requirement,
            file_count=selection_context.file_count or 0,
            has_inline_text=selection_context.has_inline_text,
            has_conversation_material=selection_context.has_conversation_material,
            pending_clarification=selection_context.pending_clarification,
        )
        if model_choice is not None and model_choice.task_type is not None:
            structured = StructuredRequirement(
                task_type=model_choice.task_type,
                turn_relation=model_choice.turn_relation,
                source_mode=model_choice.source_mode,
                memory_mode=model_choice.memory_mode,
                selected_skills=[skill.name for skill in selected_skills],
                primary_skill=primary_skill.name,
                needs_clarification=model_choice.needs_clarification,
                clarification_questions=model_choice.clarification_questions,
                missing_inputs=model_choice.missing_inputs,
                confidence=model_choice.confidence,
                reason_summary=model_choice.reason_summary,
            )
        else:
            structured = structured.model_copy(
                update={
                    "selected_skills": [skill.name for skill in selected_skills],
                    "primary_skill": primary_skill.name,
                }
            )
        return SkillSelection(
            selected=primary_skill,
            selected_skills=selected_skills,
            candidates=candidates,
            used_fallback=used_fallback,
            plan=plan,
            reason_summary=reason,
            model_used=model_used,
            requirement=structured,
        )

    def _hard_filter(
        self,
        requirement: str,
        context: SkillSelectionContext,
    ) -> list[LoadedSkill]:
        normalized = requirement.casefold()
        eligible: list[LoadedSkill] = []
        for skill in self._registry.list_all():
            policy = skill.routing_policy
            if context.permitted_skills is not None and skill.name not in context.permitted_skills:
                continue
            if context.permitted_tools is not None and not set(skill.allowed_tools) <= set(context.permitted_tools):
                continue
            # Missing material is an execution-readiness concern, not a reason to
            # hide an otherwise suitable Skill from semantic/rule recall.
            if (
                context.file_count is not None
                and policy.max_files is not None
                and context.file_count > policy.max_files
            ):
                continue
            if any(condition.casefold() in normalized for condition in skill.non_trigger_conditions):
                continue
            eligible.append(skill)
        return eligible

    async def _hybrid_rank(
        self,
        requirement: str,
        skills: list[LoadedSkill],
    ) -> list[SkillCandidate]:
        normalized = requirement.casefold()
        rule_scores = {
            skill.name: float(
                2 * sum(keyword.casefold() in normalized for keyword in skill.routing_keywords)
                + sum(condition.casefold() in normalized for condition in skill.trigger_conditions)
            )
            for skill in skills
        }
        max_rule = max(rule_scores.values(), default=0.0)
        semantic_scores = {skill.name: 0.0 for skill in skills}
        if self._embeddings is not None and skills:
            try:
                if self._candidate_vectors is None:
                    all_skills = self._registry.list_all()
                    texts = [self._routing_text(skill) for skill in all_skills]
                    vectors = await self._embeddings.embed_batch(texts)
                    self._candidate_vectors = {
                        skill.name: vector for skill, vector in zip(all_skills, vectors, strict=True)
                    }
                query_vector = await self._embeddings.embed(requirement)
                semantic_scores = {
                    skill.name: max(0.0, self._cosine(query_vector, self._candidate_vectors[skill.name]))
                    for skill in skills
                }
            except Exception:
                semantic_scores = {skill.name: 0.0 for skill in skills}
        ranked = [
            SkillCandidate(
                name=skill.name,
                description=skill.description,
                score=(0.65 * (rule_scores[skill.name] / max_rule) if max_rule else 0.0)
                + 0.35 * semantic_scores[skill.name],
                rule_score=rule_scores[skill.name],
                semantic_score=semantic_scores[skill.name],
            )
            for skill in skills
        ]
        ranked.sort(key=lambda item: (-item.score, item.name))
        return ranked

    async def _model_select(
        self,
        requirement: str,
        candidates: tuple[SkillCandidate, ...],
        context: SkillSelectionContext,
    ) -> tuple[list[str], str | None, str, bool, _ModelSkillChoice | None]:
        if self._decision_llm is None or not candidates:
            return [], None, "", True, None
        candidate_payload = [
            {"name": item.name, "description": item.description, "score": round(item.score, 4)}
            for item in candidates
        ]
        prompt = (
            "一次完成结构化需求理解和 Skill 选择。不要把出现‘论文’一词等同于必须检索文件；"
            "润色/改写可使用用户本轮粘贴文本或明确指向的历史原文。"
            "先判断当前轮是新任务、延续、修改上一输出还是回答澄清，再判断材料来源和 Memory 范围。"
            "从候选 Skill 中选择 0 到 "
            f"{context.budget.max_skills} 个。只能返回候选名称；不需要专用 Skill 时返回空数组。"
            "primary_skill 必须属于 selected_skills。只给简短可公开理由，不输出思维过程。\n"
            f"用户需求：{requirement}\n"
            f"待回答的上一澄清任务：{context.previous_request or '无'}\n"
            f"当前有文件：{bool(context.file_count)}；当前有较长粘贴文本：{context.has_inline_text}；"
            f"会话内有可定位原文：{context.has_conversation_material}\n"
            f"候选：{json.dumps(candidate_payload, ensure_ascii=False)}"
        )
        try:
            raw = await self._decision_llm.generate_with_schema(
                prompt,
                system_prompt="你是受约束的 Skill 路由器，只输出符合 Schema 的 JSON。",
                response_schema=_ModelSkillChoice.model_json_schema(),
                max_tokens=320,
                temperature=0.0,
            )
            choice = _ModelSkillChoice.model_validate_json(raw)
            names = list(dict.fromkeys(choice.selected_skills))[: context.budget.max_skills]
            primary = choice.primary_skill if choice.primary_skill in names else (names[0] if names else None)
            return names, primary, choice.reason_summary, False, choice
        except (RuntimeError, ValueError, ValidationError, json.JSONDecodeError):
            return [], None, "", True, None

    @staticmethod
    def _routing_text(skill: LoadedSkill) -> str:
        return "；".join(
            [skill.name, skill.description, *skill.routing_keywords, *skill.trigger_conditions]
        )

    @staticmethod
    def _cosine(left: list[float], right: list[float]) -> float:
        if not left or len(left) != len(right):
            return 0.0
        denominator = math.sqrt(sum(value * value for value in left)) * math.sqrt(
            sum(value * value for value in right)
        )
        return sum(a * b for a, b in zip(left, right, strict=True)) / denominator if denominator else 0.0

    def _load_selected(self, name: str) -> LoadedSkill:
        skill = self._registry.get(name)
        if skill is None:
            raise ValueError(f"Skill not found: {name}")
        self.loaded_instruction_names.add(name)
        return skill
