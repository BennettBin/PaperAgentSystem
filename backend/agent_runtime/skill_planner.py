"""Deterministic planning and validation for a selected set of Skills."""

from __future__ import annotations

from dataclasses import dataclass

from backend.core.errors import ErrorCode, ProjectError
from backend.skills.loader import LoadedSkill, SkillRegistry


@dataclass(frozen=True, slots=True)
class SkillPlanStep:
    skill_name: str
    depends_on: tuple[str, ...]
    parallel_group: int


@dataclass(frozen=True, slots=True)
class SkillExecutionPlan:
    steps: tuple[SkillPlanStep, ...]
    primary_skill: str
    replan_count: int = 0

    def topological_order(self) -> tuple[str, ...]:
        remaining = {step.skill_name: set(step.depends_on) for step in self.steps}
        order: list[str] = []
        while remaining:
            ready = sorted(name for name, deps in remaining.items() if not deps)
            if not ready:
                raise ProjectError(ErrorCode.INVALID_ARGUMENT, "Skill plan contains a cycle")
            order.extend(ready)
            for name in ready:
                remaining.pop(name)
            for deps in remaining.values():
                deps.difference_update(ready)
        return tuple(order)


@dataclass(frozen=True, slots=True)
class SkillPlanBudget:
    max_skills: int = 3
    max_parallel: int = 2
    max_replans: int = 2


class DeterministicSkillPlanner:
    """Compile model-selected names into a bounded, permission-checked DAG."""

    def __init__(self, registry: SkillRegistry) -> None:
        self._registry = registry

    def create(
        self,
        selected_names: list[str],
        *,
        primary_skill: str | None,
        permitted_skills: frozenset[str] | None,
        permitted_tools: frozenset[str] | None,
        budget: SkillPlanBudget,
        replan_count: int = 0,
    ) -> SkillExecutionPlan:
        if budget.max_skills < 1 or budget.max_parallel < 1:
            raise ProjectError(
                ErrorCode.INVALID_ARGUMENT,
                "Skill and parallel budgets must be positive",
            )
        if replan_count < 0 or replan_count > budget.max_replans:
            raise ProjectError(
                ErrorCode.RESOURCE_EXHAUSTED,
                "Skill replan budget exceeded",
            )
        names = list(dict.fromkeys(selected_names))
        if not names:
            raise ProjectError(ErrorCode.INVALID_ARGUMENT, "Skill plan cannot be empty")
        if len(names) > budget.max_skills:
            raise ProjectError(ErrorCode.RESOURCE_EXHAUSTED, "Skill budget exceeded")
        skills = [self._get_permitted(name, permitted_skills, permitted_tools) for name in names]
        primary = primary_skill if primary_skill in names else names[0]

        exclusive = [skill for skill in skills if skill.routing_policy.exclusive]
        if exclusive and len(skills) > 1:
            primary_definition = next(skill for skill in skills if skill.name == primary)
            skills = (
                [primary_definition]
                if primary_definition.routing_policy.exclusive
                else [skill for skill in skills if not skill.routing_policy.exclusive]
            )
            names = [skill.name for skill in skills]

        formats = {skill.output_contract.format for skill in skills}
        if "object" in formats and len(formats) > 1 or (
            "object" in formats and len(skills) > 1
        ):
            chosen = next(skill for skill in skills if skill.name == primary)
            skills = [chosen]
            names = [chosen.name]

        selected = set(names)
        dependency_map = {
            skill.name: tuple(
                dependency
                for dependency in skill.routing_policy.runs_after
                if dependency in selected
            )
            for skill in skills
        }
        group_by_name: dict[str, int] = {}
        unresolved = set(names)
        while unresolved:
            ready = sorted(
                name
                for name in unresolved
                if set(dependency_map[name]) <= set(group_by_name)
            )
            if not ready:
                raise ProjectError(ErrorCode.INVALID_ARGUMENT, "Skill plan contains a cycle")
            for index, name in enumerate(ready):
                dependency_group = max(
                    (group_by_name[item] + 1 for item in dependency_map[name]),
                    default=0,
                )
                group_by_name[name] = dependency_group + index // budget.max_parallel
                unresolved.remove(name)

        plan = SkillExecutionPlan(
            steps=tuple(
                SkillPlanStep(name, dependency_map[name], group_by_name[name])
                for name in sorted(names, key=lambda item: (group_by_name[item], item))
            ),
            primary_skill=primary,
            replan_count=replan_count,
        )
        plan.topological_order()
        return plan

    def _get_permitted(
        self,
        name: str,
        permitted_skills: frozenset[str] | None,
        permitted_tools: frozenset[str] | None,
    ) -> LoadedSkill:
        skill = self._registry.get(name)
        if skill is None:
            raise ProjectError(ErrorCode.SKILL_NOT_FOUND, f"Skill not found: {name}")
        if permitted_skills is not None and name not in permitted_skills:
            raise ProjectError(ErrorCode.PERMISSION_DENIED, f"Skill is not permitted: {name}")
        if permitted_tools is not None:
            forbidden = set(skill.allowed_tools) - set(permitted_tools)
            if forbidden:
                raise ProjectError(
                    ErrorCode.PERMISSION_DENIED,
                    f"Skill requires forbidden Tools: {sorted(forbidden)}",
                )
        return skill
