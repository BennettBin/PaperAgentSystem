import asyncio
from dataclasses import dataclass
from enum import Enum


class FaultMode(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    TIMEOUT = "timeout"
    PARTIAL = "partial"


@dataclass
class FakeControl:
    mode: FaultMode = FaultMode.SUCCESS
    delay_seconds: float = 0

    async def checkpoint(self, operation: str) -> None:
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        if self.mode is FaultMode.FAILURE:
            raise RuntimeError(f"Simulated failure: {operation}")
        if self.mode is FaultMode.TIMEOUT:
            raise TimeoutError(f"Simulated timeout: {operation}")

    @property
    def is_partial(self) -> bool:
        return self.mode is FaultMode.PARTIAL
