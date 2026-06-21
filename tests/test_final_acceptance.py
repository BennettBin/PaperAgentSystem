import json
from pathlib import Path

from evaluation.final_acceptance import (
    AcceptanceScenario,
    FinalAcceptanceRunner,
    ScenarioExecution,
)


def test_final_acceptance_calculates_required_system_gates(tmp_path: Path) -> None:
    scenarios = [
        AcceptanceScenario(f"scenario-{index}", (f"tests/test_{index}.py",))
        for index in range(10)
    ]

    def execute(scenario: AcceptanceScenario) -> ScenarioExecution:
        return ScenarioExecution(
            scenario=scenario.name,
            passed=scenario.name != "scenario-9",
            duration_seconds=0.01,
            timed_out=False,
            output="ok",
        )

    report = FinalAcceptanceRunner(scenarios, executor=execute).run(
        commit="abc123",
        citation_support_rate=0.92,
        deletion_unavailable=True,
        adapter_free=True,
    )
    output = tmp_path / "acceptance.json"
    report.write_json(output)
    payload = json.loads(output.read_text(encoding="utf-8"))

    assert payload["metrics"]["completion_rate"] == 0.9
    assert payload["metrics"]["dead_loop_rate"] == 0
    assert payload["metrics"]["citation_support_rate"] == 0.92
    assert payload["gates"]["completion_rate"] is True
    assert payload["gates"]["dead_loop_rate"] is True
    assert payload["gates"]["citation_support_rate"] is True
    assert payload["gates"]["deletion_unavailable"] is True
    assert payload["gates"]["adapter_free"] is True
    assert payload["passed"] is True
