"""
Tool definition and management
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class ToolParameter:
    """Tool parameter definition"""
    name: str
    type: str
    description: str
    required: bool = True
    default: Optional[Any] = None


@dataclass
class Tool:
    """Tool definition"""
    name: str
    description: str
    parameters: list[ToolParameter]
    execute_fn: Callable[..., Awaitable[Any]]

    async def execute(self, **kwargs: Any) -> Any:
        """Execute tool with given parameters"""
        return await self.execute_fn(**kwargs)


class ToolRegistry:
    """Registry for managing tools"""

    def __init__(self) -> None:
        self.tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Register a tool"""
        self.tools[tool.name] = tool

    def get(self, tool_name: str) -> Optional[Tool]:
        """Get tool by name"""
        return self.tools.get(tool_name)

    def list_all(self) -> list[Tool]:
        """List all registered tools"""
        return list(self.tools.values())

    async def execute(self, tool_name: str, **kwargs: Any) -> Any:
        """Execute a tool"""
        tool = self.get(tool_name)
        if tool is None:
            raise ValueError(f"Tool not found: {tool_name}")
        return await tool.execute(**kwargs)


# Global tool registry
_global_tool_registry = ToolRegistry()


def get_tool_registry() -> ToolRegistry:
    """Get global tool registry"""
    return _global_tool_registry
