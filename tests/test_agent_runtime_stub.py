import pytest

from agent_runtime.stub import AgentRuntimeStub, BudgetPolicy, RuntimeContext, RuntimeState


class RecordingPersistence:
    def __init__(self):
        self.states = []

    async def save(self, context):
        self.states.append(context.state)


class FakeCancellation:
    def __init__(self, cancelled=False):
        self.cancelled = cancelled
        self.checks = 0

    async def is_cancelled(self, task_id):
        self.checks += 1
        return self.cancelled


@pytest.mark.asyncio
async def test_runtime_node_order_and_state_persistence():
    persistence = RecordingPersistence()
    cancellation = FakeCancellation()
    runtime = AgentRuntimeStub(persistence, cancellation)

    result = await runtime.run(RuntimeContext(task_id="task-1", request="analyze"))

    assert result.state is RuntimeState.COMPLETED
    assert result.events == [
        "context_builder",
        "requirement_clarifier",
        "skill_selector",
        "planner",
        "executor",
        "verifier",
        "termination",
    ]
    assert len(persistence.states) == len(result.events) + 1
    assert cancellation.checks == len(result.events)


@pytest.mark.asyncio
async def test_runtime_checks_cancellation_before_actions():
    persistence = RecordingPersistence()
    runtime = AgentRuntimeStub(persistence, FakeCancellation(cancelled=True))

    result = await runtime.run(RuntimeContext(task_id="task-2", request="cancel"))

    assert result.state is RuntimeState.CANCELLED
    assert result.events == []


@pytest.mark.asyncio
async def test_runtime_stops_at_budget():
    persistence = RecordingPersistence()
    runtime = AgentRuntimeStub(
        persistence,
        FakeCancellation(),
        budget=BudgetPolicy(max_steps=2),
    )

    result = await runtime.run(RuntimeContext(task_id="task-3", request="budget"))

    assert result.state is RuntimeState.FAILED
    assert result.result == {"error": "budget_exhausted"}
    assert len(result.events) == 2
