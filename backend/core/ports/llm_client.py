"""
LLM 和 Embedding 相关 Port 定义
"""

from abc import ABC, abstractmethod
from typing import Optional


class LLMClient(ABC):
    """LLM 客户端 Port

    用于调用语言模型（生成、规划等）。
    """

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        top_p: float = 0.95,
        stop_sequences: Optional[list[str]] = None,
    ) -> str:
        """生成文本"""
        pass

    @abstractmethod
    async def generate_with_schema(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        response_schema: Optional[dict] = None,
        max_tokens: int = 2048,
        temperature: float = 0.7,
    ) -> str:
        """生成符合 Schema 的文本（JSON）"""
        pass


class EmbeddingClient(ABC):
    """Embedding 客户端 Port

    用于文本向量化。
    """

    @abstractmethod
    async def embed(self, text: str) -> list[float]:
        """获取文本的向量表示"""
        pass

    @abstractmethod
    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """批量获取向量"""
        pass


class RerankerClient(ABC):
    """Reranker 客户端 Port

    用于混合检索的精排。
    """

    @abstractmethod
    async def rerank(
        self, query: str, documents: list[str], top_k: int = 5
    ) -> list[tuple[int, float]]:
        """重排候选文档

        返回 (原始索引, 相关性分数) 的列表
        """
        pass
