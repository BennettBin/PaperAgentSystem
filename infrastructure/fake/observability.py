"""
Fake Observability implementations
"""

from core.ports.observability import TraceWriter
from typing import Optional


class FakeTraceWriter(TraceWriter):
    def __init__(self):
        self.traces: list = []
        self.model_calls: list = []

    async def write_trace(
        self,
        trace_id: str,
        span_name: str,
        data: dict,
        parent_span_id: Optional[str] = None,
        duration_ms: int = 0,
        error: Optional[str] = None,
    ) -> None:
        self.traces.append({
            "trace_id": trace_id,
            "span_name": span_name,
            "data": data,
            "parent_span_id": parent_span_id,
            "duration_ms": duration_ms,
            "error": error,
        })

    async def write_model_call(
        self,
        trace_id: str,
        model_id: str,
        prompt: str,
        response: str,
        tokens_in: int,
        tokens_out: int,
        latency_ms: int,
    ) -> None:
        self.model_calls.append({
            "trace_id": trace_id,
            "model_id": model_id,
            "prompt": prompt,
            "response": response,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "latency_ms": latency_ms,
        })

    def get_traces(self) -> list:
        return self.traces

    def get_model_calls(self) -> list:
        return self.model_calls
