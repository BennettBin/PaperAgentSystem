"""
Skill、Tool 和 Model 注册 Port 定义
"""

from abc import ABC, abstractmethod
from typing import Optional, Any


class ToolDefinition(ABC):
    """Tool 定义基类"""

    @property
    @abstractmethod
    def name(self) -> str:
        """Tool 名称"""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Tool 描述"""
        pass

    @property
    @abstractmethod
    def parameters_schema(self) -> dict:
        """参数 Schema (JSON Schema)"""
        pass


class ToolRegistry(ABC):
    """Tool 注册表 Port"""

    @abstractmethod
    async def register(self, tool: ToolDefinition) -> None:
        """注册 Tool"""
        pass

    @abstractmethod
    async def get(self, tool_name: str) -> Optional[ToolDefinition]:
        """获取 Tool 定义"""
        pass

    @abstractmethod
    async def list_all(self) -> list[ToolDefinition]:
        """列出所有 Tool"""
        pass

    @abstractmethod
    async def verify_access(self, tool_name: str, permissions: list[str]) -> bool:
        """验证 Tool 访问权限"""
        pass


class SkillDefinition(ABC):
    """Skill 定义基类"""

    @property
    @abstractmethod
    def name(self) -> str:
        """Skill 名称"""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Skill 描述"""
        pass

    @property
    @abstractmethod
    def required_tools(self) -> list[str]:
        """所需 Tool 列表"""
        pass

    @property
    @abstractmethod
    def model_profile(self) -> str:
        """使用的模型 Profile"""
        pass


class SkillRegistry(ABC):
    """Skill 注册表 Port"""

    @abstractmethod
    async def register(self, skill: SkillDefinition) -> None:
        """注册 Skill"""
        pass

    @abstractmethod
    async def get(self, skill_name: str) -> Optional[SkillDefinition]:
        """获取 Skill 定义"""
        pass

    @abstractmethod
    async def list_all(self) -> list[SkillDefinition]:
        """列出所有 Skill"""
        pass


class ModelProfile(ABC):
    """模型 Profile"""

    @property
    @abstractmethod
    def profile_id(self) -> str:
        """Profile ID"""
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Profile 名称"""
        pass

    @property
    @abstractmethod
    def status(self) -> str:
        """状态: development / evaluation / production"""
        pass

    @property
    @abstractmethod
    def context_length(self) -> int:
        """上下文长度"""
        pass

    @property
    @abstractmethod
    def max_tokens(self) -> int:
        """最大生成 Token 数"""
        pass

    @property
    @abstractmethod
    def config(self) -> dict:
        """模型配置（temperature、top_p 等）"""
        pass


class ModelRegistry(ABC):
    """模型注册表 Port"""

    @abstractmethod
    async def get_profile(self, profile_name: str) -> Optional[ModelProfile]:
        """获取模型 Profile"""
        pass

    @abstractmethod
    async def list_profiles(self) -> list[ModelProfile]:
        """列出所有 Profile"""
        pass

    @abstractmethod
    async def register_profile(self, profile: ModelProfile) -> None:
        """注册新 Profile"""
        pass

    @abstractmethod
    async def get_default_profile(self) -> ModelProfile:
        """获取默认 Profile"""
        pass
