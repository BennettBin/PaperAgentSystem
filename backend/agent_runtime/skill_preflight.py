"""Deterministic input-readiness checks performed after Skill selection."""

from __future__ import annotations

from dataclasses import dataclass

from backend.agent_runtime.structured_requirement import SourceMode, StructuredRequirement
from backend.skills.loader import LoadedSkill


@dataclass(frozen=True, slots=True)
class SkillInputSnapshot:
    file_count: int = 0
    has_inline_text: bool = False
    has_conversation_material: bool = False


@dataclass(frozen=True, slots=True)
class SkillPreflightResult:
    ready: bool
    missing_inputs: tuple[str, ...] = ()
    clarification_questions: tuple[str, ...] = ()


class SkillPreflight:
    def check(
        self,
        skill: LoadedSkill,
        requirement: StructuredRequirement,
        inputs: SkillInputSnapshot,
    ) -> SkillPreflightResult:
        policy = skill.input_policy
        if inputs.file_count < policy.min_files:
            return self._missing(policy.missing_source_prompt, "uploaded_files")
        if policy.max_files is not None and inputs.file_count > policy.max_files:
            return SkillPreflightResult(
                False,
                ("too_many_files",),
                (f"该任务最多支持 {policy.max_files} 个文件，请缩小文件范围。",),
            )
        if not policy.source_required:
            return SkillPreflightResult(True)
        available = {
            SourceMode.INLINE_TEXT.value: inputs.has_inline_text,
            SourceMode.CONVERSATION_MATERIAL.value: inputs.has_conversation_material,
            SourceMode.UPLOADED_FILES.value: inputs.file_count > 0,
            SourceMode.EXTERNAL.value: requirement.source_mode is SourceMode.EXTERNAL,
        }
        if any(available.get(source, False) for source in policy.accepted_sources):
            return SkillPreflightResult(True)
        return self._missing(policy.missing_source_prompt, "source_material")

    @staticmethod
    def _missing(prompt: str, field: str) -> SkillPreflightResult:
        return SkillPreflightResult(False, (field,), (prompt,))
