"""
存储和队列相关 Port 定义
"""

from abc import ABC, abstractmethod
from typing import Optional
from io import BytesIO


class ObjectStore(ABC):
    """对象存储 Port

    用于上传、下载和管理文件。
    """

    @abstractmethod
    async def upload(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> str:
        """上传文件，返回可访问的 URL"""
        pass

    @abstractmethod
    async def upload_stream(
        self, key: str, stream: BytesIO, content_type: str = "application/octet-stream"
    ) -> str:
        """流式上传文件"""
        pass

    @abstractmethod
    async def download(self, key: str) -> bytes:
        """下载文件"""
        pass

    @abstractmethod
    async def download_stream(self, key: str) -> BytesIO:
        """流式下载文件"""
        pass

    @abstractmethod
    async def delete(self, key: str) -> None:
        """删除文件"""
        pass

    @abstractmethod
    async def exists(self, key: str) -> bool:
        """检查文件是否存在"""
        pass

    @abstractmethod
    async def get_temporary_url(self, key: str, expires_in_seconds: int = 3600) -> str:
        """获取临时访问 URL"""
        pass


class TaskQueue(ABC):
    """任务队列 Port

    用于后台任务执行。
    """

    @abstractmethod
    async def enqueue(
        self,
        task_type: str,
        payload: dict,
        idempotency_key: str,
        priority: int = 0,
    ) -> str:
        """投递任务，返回任务 ID"""
        pass

    @abstractmethod
    async def get_status(self, task_id: str) -> str:
        """获取任务状态 (queued, running, completed, failed)"""
        pass

    @abstractmethod
    async def get_result(self, task_id: str) -> Optional[dict]:
        """获取任务结果"""
        pass

    @abstractmethod
    async def cancel(self, task_id: str) -> bool:
        """取消任务"""
        pass


class EventPublisher(ABC):
    """事件发布 Port

    用于发布系统事件。
    """

    @abstractmethod
    async def publish(
        self, event_type: str, data: dict, channel: Optional[str] = None
    ) -> None:
        """发布事件"""
        pass

    @abstractmethod
    async def subscribe(self, channel: str) -> list[dict]:
        """订阅频道（仅用于测试）"""
        pass
