from dataclasses import dataclass, field

from agent_runtime.stub import AgentRuntimeStub, RuntimeContext
from core.ports.storage import TaskQueue

SCENARIOS = {
    "direct_execution",
    "clarification_resume",
    "subagents_partial_failure",
    "verification_replan",
    "cancel_retry",
    "memory_recall",
    "workspace_recall",
    "deletion_invalidation",
    "writing_artifact",
}


@dataclass
class ScenarioPersistence:
    traces: list[dict] = field(default_factory=list)

    async def save(self, context: RuntimeContext) -> None:
        self.traces.append(
            {
                "state": context.state.value,
                "steps_used": context.steps_used,
                "events": list(context.events),
            }
        )


@dataclass
class ScenarioCancellation:
    cancelled: bool = False

    async def is_cancelled(self, task_id: str) -> bool:
        return self.cancelled


class FakeScenarioRunner:
    def __init__(self, queue: TaskQueue) -> None:
        self.queue = queue

    async def run(self, scenario: str) -> dict:
        if scenario not in SCENARIOS:
            raise ValueError(f"Unknown scenario: {scenario}")
        task_id = await self.queue.enqueue(
            task_type="main_agent",
            payload={"scenario": scenario},
            idempotency_key=f"scenario:{scenario}",
        )
        persistence = ScenarioPersistence()
        cancellation = ScenarioCancellation(cancelled=scenario == "cancel_retry")
        runtime = AgentRuntimeStub(persistence, cancellation)
        context = await runtime.run(RuntimeContext(task_id=task_id, request=scenario))

        public_events = [
            {"sequence": index + 1, "type": event} for index, event in enumerate(context.events)
        ]
        details: dict[str, object] = {}
        result: dict[str, object] = {
            "scenario": scenario,
            "task_id": task_id,
            "state": context.state.value,
            "events": public_events,
            "trace": persistence.traces,
            "details": details,
        }
        if scenario == "clarification_resume":
            details.update(questions=1, resumed_original_task=True)
        elif scenario == "subagents_partial_failure":
            details.update(succeeded=2, failed=1, aggregate="partial")
        elif scenario == "verification_replan":
            details.update(replans=1, verification="passed_after_replan")
        elif scenario == "cancel_retry":
            details.update(cancelled=True, retryable=True)
        elif scenario == "memory_recall":
            details.update(source_message_id="message-early", found=True)
        elif scenario == "workspace_recall":
            details.update(workspace_entry_id="entry-script", found=True)
        elif scenario == "deletion_invalidation":
            details.update(search_results=[])
        elif scenario == "writing_artifact":
            details.update(artifact_id="artifact-fake-section", review_required=True)
        else:
            details.update(completed=True)
        return result
