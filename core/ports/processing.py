"""
文档、检索和验证 Port 定义
"""

from abc import ABC, abstractmethod
from typing import Any, Optional


class DocumentParser(ABC):
    """文档解析 Port

    支持 PDF、DOCX、Markdown 等格式。
    """

    @abstractmethod
    async def parse(self, file_data: bytes, filename: str) -> Any:
        """解析文档

        返回 {
            'text': 完整文本,
            'chunks': [{
                'text': 文本块,
                'page': 页码,
                'bbox': 边界框,
                'metadata': {}
            }],
            'metadata': {
                'title': 标题,
                'authors': 作者列表,
                'pages': 总页数,
                ...
            }
        }
        """
        pass

    @abstractmethod
    async def supports_format(self, filename: str) -> bool:
        """检查是否支持该格式"""
        pass


class Retriever(ABC):
    """检索 Port

    用于文档相似度搜索。
    """

    @abstractmethod
    async def search(
        self, query: str, top_k: int = 10, workspace_id: Optional[str] = None
    ) -> list[dict]:
        """搜索相关文档

        返回 [{
            'doc_id': 文档 ID,
            'score': 相似度分数,
            'text': 文本摘录,
            'metadata': {}
        }]
        """
        pass

    @abstractmethod
    async def index(self, doc_id: str, text: str, metadata: dict) -> None:
        """索引文档"""
        pass

    @abstractmethod
    async def delete_index(self, doc_id: str) -> None:
        """删除索引"""
        pass


class ClaimVerifier(ABC):
    """声明验证 Port

    用于验证生成的内容是否有支持的证据。
    """

    @abstractmethod
    async def verify_claim(
        self, claim: str, evidence: list[str]
    ) -> dict:
        """验证声明

        返回 {
            'is_supported': 布尔值,
            'confidence': 置信度 0-1,
            'issues': [问题列表],
            'suggestions': [修改建议]
        }
        """
        pass


class SandboxExecutor(ABC):
    """沙箱执行 Port

    用于安全执行代码或 LaTeX。MVP 版本返回"不支持"错误。
    """

    @abstractmethod
    async def execute_code(
        self, code: str, language: str = "python", timeout_seconds: int = 30
    ) -> dict:
        """执行代码

        返回 {
            'success': 布尔值,
            'stdout': 输出,
            'stderr': 错误,
            'exit_code': 退出码
        }
        """
        pass

    @abstractmethod
    async def render_latex(self, latex_code: str) -> bytes:
        """渲染 LaTeX 为 PDF"""
        pass
