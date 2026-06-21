"""Structured planning and bounded replanning."""

from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.errors import ErrorCode, ProjectError


@dataclass(frozen=True, slots=True)
class RegistrySnapshot:
    skills: set[str]
    tools: set[str]
    subagents: set[str] = field(default_factory=set)


class PlanStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_id: str
    action: str
    skill_name: str | None = None
    tool_name: str | None = None
    subagent_name: str | None = None
    depends_on: list[str] = Field(default_factory=list)
    completion_condition: str = Field(min_length=1)

    @model_validator(mode="after")
    def one_executor(self) -> "PlanStep":
        executors = (self.skill_name, self.tool_name, self.subagent_name)
        if sum(value is not None for value in executors) > 1:
            raise ValueError("A step must invoke at most one Skill, Tool or sub Agent")
        return self


class ExecutionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal: str
    steps: list[PlanStep] = Field(min_length=1, max_length=8)
    replan_count: int = Field(default=0, ge=0, le=2)

    def topological_order(self) -> list[str]:
        ids = {step.step_id for step in self.steps}
        if len(ids) != len(self.steps):
            raise ProjectError(ErrorCode.INVALID_ARGUMENT, "Plan step IDs must be unique")
        incoming = {step.step_id: set(step.depends_on) for step in self.steps}
        if any(not deps <= ids for deps in incoming.values()):
            raise ProjectError(ErrorCode.INVALID_ARGUMENT, "Plan has an unknown dependency")
        order = []
        while incoming:
            ready = [step_id for step_id, deps in incoming.items() if not deps]
            if not ready:
                raise ProjectError(ErrorCode.INVALID_ARGUMENT, "Plan dependency graph has a cycle")
            for step_id in ready:
                order.append(step_id)
                incoming.pop(step_id)
            for deps in incoming.values():
                deps.difference_update(ready)
        return order

    def validate_against(self, registry: RegistrySnapshot) -> None:
        self.topological_order()
        for step in self.steps:
            if step.skill_name and step.skill_name not in registry.skills:
                raise ProjectError(
                    ErrorCode.SKILL_NOT_FOUND,
                    f"Unregistered Skill: {step.skill_name}",
                )
            if step.tool_name and step.tool_name not in registry.tools:
                raise ProjectError(
                    ErrorCode.TOOL_NOT_FOUND,
                    f"Unregistered Tool: {step.tool_name}",
                )
            if step.subagent_name and step.subagent_name not in registry.subagents:
                raise ProjectError(
                    ErrorCode.NOT_FOUND,
                    f"Unregistered sub Agent: {step.subagent_name}",
                )


class Planner:
    MAX_REPLANS = 2

    def __init__(self, registry: RegistrySnapshot) -> None:
        self._registry = registry

    def create(
        self,
        goal: str,
        skill_name: str,
        tool_names: list[str],
    ) -> ExecutionPlan:
        steps = [
            PlanStep(
                step_id="skill-1",
                action=f"Apply {skill_name}",
                skill_name=skill_name,
                completion_condition="Skill input and output contract are satisfied",
            )
        ]
        previous = "skill-1"
        for index, tool_name in enumerate(tool_names, start=1):
            step_id = f"tool-{index}"
            steps.append(
                PlanStep(
                    step_id=step_id,
                    action=f"Run {tool_name}",
                    tool_name=tool_name,
                    depends_on=[previous],
                    completion_condition=f"{tool_name} returns a valid structured result",
                )
            )
            previous = step_id
        plan = ExecutionPlan(goal=goal, steps=steps)
        plan.validate_against(self._registry)
        return plan

    def replan(
        self,
        plan: ExecutionPlan,
        *,
        failed_step_id: str,
        reason: str,
    ) -> ExecutionPlan:
        if plan.replan_count >= self.MAX_REPLANS:
            raise ProjectError(
                ErrorCode.RESOURCE_EXHAUSTED,
                "Replan limit reached",
                {"failed_step_id": failed_step_id, "reason": reason},
            )
        replacement = plan.model_copy(deep=True)
        replacement.replan_count += 1
        for step in replacement.steps:
            if step.step_id == failed_step_id:
                step.action = f"{step.action} (retry after: {reason})"
        replacement.validate_against(self._registry)
        return replacement
