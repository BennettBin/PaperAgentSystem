"""
文件实体
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Optional

from core.domain.ids import FileId, WorkspaceId


@dataclass
class File:
    """文件实体

    用户上传或系统生成的文件。
    """

    id: FileId
    workspace_id: WorkspaceId
    filename: str
    content_type: str
    size_bytes: int
    storage_path: str  # MinIO 路径
    checksum: str  # SHA-256
    created_at: datetime
    updated_at: datetime
    is_deleted: bool = False
    metadata: dict = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        workspace_id: WorkspaceId,
        filename: str,
        content_type: str,
        size_bytes: int,
        storage_path: str,
        checksum: str,
        metadata: Optional[dict] = None,
    ) -> "File":
        """创建新文件"""
        now = datetime.now(UTC)
        return cls(
            id=FileId.generate(),
            workspace_id=workspace_id,
            filename=filename,
            content_type=content_type,
            size_bytes=size_bytes,
            storage_path=storage_path,
            checksum=checksum,
            created_at=now,
            updated_at=now,
            metadata=metadata or {},
        )
