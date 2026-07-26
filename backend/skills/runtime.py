"""Validated structured lifecycle for production Skill and Tool invocation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from backend.agent_runtime.skill_planner import SkillExecutionPlan
from backend.agent_runtime.skill_selector import (
    SkillSelection,
    SkillSelectionContext,
    SkillSelector,
)
from backend.skills.loader import (
    LoadedSkill,
    SkillRegistry,
    SkillToolBinding,
    _validate_structured_value,
)


@dataclass(frozen=True, slots=True)
class SkillActivation:
    skill: LoadedSkill
    input_data: Any
    selection: SkillSelection
    skills: tuple[LoadedSkill, ...] = ()
    plan: SkillExecutionPlan | None = None


class SkillRuntime:
    """The supported Skill entrypoint with manifest-declared structured contracts."""

    def __init__(self, selector: SkillSelector, registry: SkillRegistry) -> None:
        self._selector = selector
        self._registry = registry

    async def activate(
        self,
        requirement: str,
        input_data: Any,
        trace_id: str,
        *,
        requested_skill: str | None = None,
        selection_context: SkillSelectionContext | None = None,
    ) -> SkillActivation:
        if requested_skill:
            selected = self._registry.get(requested_skill)
            if selected is None:
                raise ValueError(f"Skill not found: {requested_skill}")
            selection = SkillSelection(selected, (), False, (selected,))
        else:
            selection = await self._selector.select(requirement, selection_context)
        selected_skills = selection.selected_skills or (selection.selected,)
        activated: list[LoadedSkill] = []
        for selected_skill in selected_skills:
            try:
                _validate_structured_value(input_data, selected_skill.input_contract)
            except ValueError as exc:
                raise ValueError(f"Skill input is invalid: {exc}") from exc
            activated.append(await self._registry.activate(selected_skill.name, trace_id))
        primary = next(
            skill for skill in activated if skill.name == selection.selected.name
        )
        return SkillActivation(
            primary,
            input_data,
            selection,
            tuple(activated),
            selection.plan,
        )

    async def complete(
        self,
        activation: SkillActivation,
        output_data: Any,
        trace_id: str,
    ) -> Any:
        self.validate_output(activation, output_data)
        for skill in activation.skills or (activation.skill,):
            await self._registry.trace_complete(skill, trace_id, "completed")
        return output_data

    def validate_output(
        self,
        activation: SkillActivation,
        output_data: Any,
    ) -> None:
        """Validate a generated result without completing the Skill lifecycle."""
        for skill in activation.skills or (activation.skill,):
            try:
                _validate_structured_value(output_data, skill.output_contract)
            except ValueError as exc:
                raise ValueError(f"Skill output is invalid for {skill.name}: {exc}") from exc

    async def start_tool(
        self,
        activation: SkillActivation,
        tool_name: str,
        arguments: dict[str, Any],
        trace_id: str,
    ) -> SkillToolBinding:
        active_skills = activation.skills or (activation.skill,)
        binding = next(
            (
                tool
                for skill in active_skills
                for tool in skill.tools
                if tool.name == tool_name
            ),
            None,
        )
        if binding is None:
            raise ValueError(
                f"Tool is not allowed by active Skills: {tool_name}"
            )
        try:
            binding.input_model.model_validate(arguments)
        except ValidationError as exc:
            await self._registry.trace_tool(
                trace_id,
                "skill.tool.rejected",
                {
                    "skill_name": activation.skill.name,
                    "skill_version": activation.skill.version,
                    "tool_name": tool_name,
                    "parameters_valid": False,
                },
                error=str(exc),
            )
            raise ValueError(f"Tool input is invalid: {exc}") from exc
        await self._registry.trace_tool(
            trace_id,
            "skill.tool.started",
            {
                "skill_name": activation.skill.name,
                "skill_version": activation.skill.version,
                "tool_name": tool_name,
                "parameters_valid": True,
                "implementation": binding.implementation,
            },
        )
        return binding

    async def complete_tool(
        self,
        binding: SkillToolBinding,
        output: dict[str, Any],
        trace_id: str,
    ) -> dict[str, Any]:
        try:
            binding.output_model.model_validate(output)
        except ValidationError as exc:
            raise ValueError(f"Tool output is invalid: {exc}") from exc
        await self._registry.trace_tool(
            trace_id,
            "skill.tool.completed",
            {"tool_name": binding.name, "output_valid": True},
        )
        return output
