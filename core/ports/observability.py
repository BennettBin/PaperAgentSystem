"""
观测和工具类 Port 定义
"""

from abc import ABC, abstractmethod
from typing import Optional, Any
from datetime import datetime


class TraceWriter(ABC):
    """Trace 写入 Port

    用于记录 Agent 执行的完整 Trace。
    """

    @abstractmethod
    async def write_trace(
        self,
        trace_id: str,
        span_name: str,
        data: dict,
        parent_span_id: Optional[str] = None,
        duration_ms: int = 0,
        error: Optional[str] = None,
    ) -> None:
        """写入 Trace 数据"""
        pass

    @abstractmethod
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
        """写入模型调用 Trace"""
        pass


class Clock(ABC):
    """时钟 Port

    用于获取当前时间（便于测试）。
    """

    @abstractmethod
    def now(self) -> datetime:
        """获取当前 UTC 时间"""
        pass

    @abstractmethod
    def now_timestamp(self) -> int:
        """获取当前时间戳（秒）"""
        pass


class IdGenerator(ABC):
    """ID 生成器 Port

    用于生成各种 ID（便于扩展）。
    """

    @abstractmethod
    def generate_id(self, prefix: str = "") -> str:
        """生成 ID"""
        pass

    @abstractmethod
    def generate_request_id(self) -> str:
        """生成请求 ID"""
        pass

    @abstractmethod
    def generate_trace_id(self) -> str:
        """生成 Trace ID"""
        pass
