"""
用户和权限实体
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Optional

from core.domain.ids import UserId, WorkspaceId


@dataclass
class User:
    """用户实体"""

    id: UserId
    email: str
    name: str
    created_at: datetime
    updated_at: datetime
    is_active: bool = True

    @classmethod
    def create(cls, email: str, name: str) -> "User":
        """创建新用户"""
        now = datetime.now(UTC)
        return cls(
            id=UserId.generate(),
            email=email,
            name=name,
            created_at=now,
            updated_at=now,
        )


@dataclass
class Workspace:
    """工作区实体

    用户可以有多个工作区，每个工作区是一个独立的数据隔离单元。
    """

    id: WorkspaceId
    user_id: UserId
    name: str
    description: Optional[str]
    created_at: datetime
    updated_at: datetime
    is_active: bool = True

    @classmethod
    def create(cls, user_id: UserId, name: str, description: Optional[str] = None) -> "Workspace":
        """创建新工作区"""
        now = datetime.now(UTC)
        return cls(
            id=WorkspaceId.generate(),
            user_id=user_id,
            name=name,
            description=description,
            created_at=now,
            updated_at=now,
        )
