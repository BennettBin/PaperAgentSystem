"""Measured Tool-argument validity from explicit validation traces."""

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True, slots=True)
class ToolParameterValidity:
    valid_calls: int
    total_calls: int

    @property
    def rate(self) -> float | None:
        if self.total_calls == 0:
            return None
        return self.valid_calls / self.total_calls


def calculate_tool_parameter_validity(
    traces: Iterable[dict[str, Any]],
) -> ToolParameterValidity:
    outcomes = [
        trace.get("data", {}).get("parameters_valid")
        for trace in traces
        if isinstance(trace.get("data"), dict)
        and isinstance(trace["data"].get("parameters_valid"), bool)
    ]
    return ToolParameterValidity(
        valid_calls=sum(value is True for value in outcomes),
        total_calls=len(outcomes),
    )
