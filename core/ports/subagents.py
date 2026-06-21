"""
Sub-agent definition and management
"""

from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any
from dataclasses import dataclass


@dataclass
class SubAgentDefinition:
    """Sub-agent definition"""
    name: str
    version: str
    description: str
    parent_skills: List[str]
    model_profile: str
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class SubAgent(ABC):
    """Base class for sub-agents"""
    
    @property
    @abstractmethod
    def definition(self) -> SubAgentDefinition:
        """Get sub-agent definition"""
        pass
    
    @abstractmethod
    async def execute(self, task_id: str, input_data: dict) -> dict:
        """Execute sub-agent"""
        pass


class SubAgentRegistry:
    """Registry for managing sub-agents"""
    
    def __init__(self):
        self.agents: Dict[str, SubAgent] = {}
        self.definitions: Dict[str, SubAgentDefinition] = {}
    
    def register(self, agent: SubAgent) -> None:
        """Register a sub-agent"""
        definition = agent.definition
        self.agents[definition.name] = agent
        self.definitions[definition.name] = definition
    
    def get(self, agent_name: str) -> Optional[SubAgent]:
        """Get sub-agent by name"""
        return self.agents.get(agent_name)
    
    def get_definition(self, agent_name: str) -> Optional[SubAgentDefinition]:
        """Get sub-agent definition"""
        return self.definitions.get(agent_name)
    
    def list_all(self) -> List[SubAgent]:
        """List all registered sub-agents"""
        return list(self.agents.values())
    
    def list_definitions(self) -> List[SubAgentDefinition]:
        """List all sub-agent definitions"""
        return list(self.definitions.values())


# Global sub-agent registry
_global_subagent_registry = SubAgentRegistry()


def get_subagent_registry() -> SubAgentRegistry:
    """Get global sub-agent registry"""
    return _global_subagent_registry
