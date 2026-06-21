from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol


class RuntimeState(str, Enum):
    RECEIVED = "received"
    UNDERSTANDING = "understanding"
    REQUIREMENT_CHECK = "requirement_check"
    SKILL_SELECTED = "skill_selected"
    PLANNED = "planned"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


@dataclass
class RuntimeContext:
    task_id: str
    request: str
    state: RuntimeState = RuntimeState.RECEIVED
    steps_used: int = 0
    events: list[str] = field(default_factory=list)
    result: dict = field(default_factory=dict)


class RuntimePersistencePort(Protocol):
    async def save(self, context: RuntimeContext) -> None: ...


class CancellationPort(Protocol):
    async def is_cancelled(self, task_id: str) -> bool: ...


@dataclass(frozen=True)
class BudgetPolicy:
    max_steps: int = 8

    def allows(self, context: RuntimeContext) -> bool:
        return context.steps_used < self.max_steps


class RuntimeNode(Protocol):
    name: str
    next_state: RuntimeState

    async def run(self, context: RuntimeContext) -> None: ...


@dataclass
class FakeDecisionNode:
    name: str
    next_state: RuntimeState

    async def run(self, context: RuntimeContext) -> None:
        context.events.append(self.name)


class ContextBuilder(FakeDecisionNode):
    def __init__(self) -> None:
        super().__init__("context_builder", RuntimeState.UNDERSTANDING)


class RequirementClarifier(FakeDecisionNode):
    def __init__(self) -> None:
        super().__init__("requirement_clarifier", RuntimeState.REQUIREMENT_CHECK)


class SkillSelector(FakeDecisionNode):
    def __init__(self) -> None:
        super().__init__("skill_selector", RuntimeState.SKILL_SELECTED)


class Planner(FakeDecisionNode):
    def __init__(self) -> None:
        super().__init__("planner", RuntimeState.PLANNED)


class Executor(FakeDecisionNode):
    def __init__(self) -> None:
        super().__init__("executor", RuntimeState.EXECUTING)

    async def run(self, context: RuntimeContext) -> None:
        await super().run(context)
        context.result = {"artifact": "fake-artifact.md"}


class Verifier(FakeDecisionNode):
    def __init__(self) -> None:
        super().__init__("verifier", RuntimeState.VERIFYING)


class Replanner(FakeDecisionNode):
    def __init__(self) -> None:
        super().__init__("replanner", RuntimeState.PLANNED)


class Termination(FakeDecisionNode):
    def __init__(self) -> None:
        super().__init__("termination", RuntimeState.COMPLETED)


class AgentRuntimeStub:
    def __init__(
        self,
        persistence: RuntimePersistencePort,
        cancellation: CancellationPort,
        budget: BudgetPolicy | None = None,
        nodes: list[RuntimeNode] | None = None,
    ) -> None:
        self.persistence = persistence
        self.cancellation = cancellation
        self.budget = budget or BudgetPolicy()
        self.nodes = nodes or [
            ContextBuilder(),
            RequirementClarifier(),
            SkillSelector(),
            Planner(),
            Executor(),
            Verifier(),
            Termination(),
        ]

    async def run(self, context: RuntimeContext) -> RuntimeContext:
        await self.persistence.save(context)
        for node in self.nodes:
            if await self.cancellation.is_cancelled(context.task_id):
                context.state = RuntimeState.CANCELLED
                await self.persistence.save(context)
                return context
            if not self.budget.allows(context):
                context.state = RuntimeState.FAILED
                context.result = {"error": "budget_exhausted"}
                await self.persistence.save(context)
                return context
            await node.run(context)
            context.steps_used += 1
            context.state = node.next_state
            await self.persistence.save(context)
        return context
