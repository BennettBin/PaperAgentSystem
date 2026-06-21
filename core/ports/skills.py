"""
Skill definition and management
"""

from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any, Callable
from dataclasses import dataclass, field


@dataclass
class SkillManifest:
    """Skill manifest definition"""
    name: str
    version: str
    description: str
    required_tools: List[str]
    model_profile: str
    input_schema: dict
    output_schema: dict
    metadata: Dict[str, Any] = field(default_factory=dict)


class Skill(ABC):
    """Base class for skills"""
    
    @property
    @abstractmethod
    def manifest(self) -> SkillManifest:
        """Get skill manifest"""
        pass
    
    @abstractmethod
    async def execute(self, input_data: dict) -> dict:
        """Execute skill"""
        pass
    
    @abstractmethod
    def validate_input(self, input_data: dict) -> bool:
        """Validate input against schema"""
        pass


class SkillRegistry:
    """Registry for managing skills"""
    
    def __init__(self):
        self.skills: Dict[str, Skill] = {}
        self.manifests: Dict[str, SkillManifest] = {}
    
    def register(self, skill: Skill) -> None:
        """Register a skill"""
        manifest = skill.manifest
        self.skills[manifest.name] = skill
        self.manifests[manifest.name] = manifest
    
    def get(self, skill_name: str) -> Optional[Skill]:
        """Get skill by name"""
        return self.skills.get(skill_name)
    
    def get_manifest(self, skill_name: str) -> Optional[SkillManifest]:
        """Get skill manifest"""
        return self.manifests.get(skill_name)
    
    def list_all(self) -> List[Skill]:
        """List all registered skills"""
        return list(self.skills.values())
    
    def list_manifests(self) -> List[SkillManifest]:
        """List all skill manifests"""
        return list(self.manifests.values())
    
    async def execute(self, skill_name: str, input_data: dict) -> dict:
        """Execute a skill"""
        skill = self.get(skill_name)
        if skill is None:
            raise ValueError(f"Skill not found: {skill_name}")
        
        if not skill.validate_input(input_data):
            raise ValueError(f"Invalid input for skill: {skill_name}")
        
        return await skill.execute(input_data)


# Global skill registry
_global_skill_registry = SkillRegistry()


def get_skill_registry() -> SkillRegistry:
    """Get global skill registry"""
    return _global_skill_registry
