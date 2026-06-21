import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from core.errors import ErrorCode, ProjectError
from core.ports.observability import TraceWriter


class SkillManifestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    description: str = Field(min_length=1)
    model_profile: str = Field(min_length=1)
    allowed_tools: list[str]
    output_schema: str
    clarification_conditions: list[str] = Field(min_length=1)
    termination_conditions: list[str] = Field(min_length=1)
    acceptance_rules: list[str] = Field(min_length=1)


@dataclass(frozen=True)
class LoadedSkill:
    name: str
    version: str
    description: str
    model_profile: str
    allowed_tools: tuple[str, ...]
    output_schema: dict[str, Any]
    instructions: str
    examples: tuple[dict[str, Any], ...]
    clarification_conditions: tuple[str, ...]
    termination_conditions: tuple[str, ...]
    acceptance_rules: tuple[str, ...]


class SkillManifestLoader:
    def __init__(
        self,
        skills_root: Path,
        registered_tools: set[str],
        available_profiles: set[str],
        fallback_profile: str = "development",
    ) -> None:
        self.skills_root = skills_root
        self.registered_tools = registered_tools
        self.available_profiles = available_profiles
        self.fallback_profile = fallback_profile

    def discover(self) -> list[LoadedSkill]:
        return [self.load(path.parent) for path in sorted(self.skills_root.glob("*/manifest.yaml"))]

    def load(self, skill_dir: Path) -> LoadedSkill:
        required_files = ("manifest.yaml", "SKILL.md", "output.schema.json", "examples.json")
        missing_files = [name for name in required_files if not (skill_dir / name).is_file()]
        if missing_files:
            raise ValueError(f"Missing Skill files: {missing_files}")
        raw = yaml.safe_load((skill_dir / "manifest.yaml").read_text("utf-8"))
        try:
            manifest = SkillManifestModel.model_validate(raw)
        except ValidationError as exc:
            raise ValueError(f"Invalid Skill manifest: {exc}") from exc
        missing_tools = set(manifest.allowed_tools) - self.registered_tools
        if missing_tools:
            raise ValueError(f"Unregistered tools: {sorted(missing_tools)}")
        profile = manifest.model_profile
        if profile not in self.available_profiles:
            profile = self.fallback_profile
        if "/" in profile or "\\" in profile:
            raise ValueError("Skill model_profile must not contain a physical path")
        schema = json.loads((skill_dir / manifest.output_schema).read_text("utf-8"))
        examples = json.loads((skill_dir / "examples.json").read_text("utf-8"))
        if not isinstance(examples, list) or not examples:
            raise ValueError("Skill examples.json must contain at least one example")
        for example in examples:
            if not isinstance(example, dict) or "input" not in example or "output" not in example:
                raise ValueError("Each Skill example requires input and output")
            _validate_json_schema(example["output"], schema)
        return LoadedSkill(
            name=manifest.name,
            version=manifest.version,
            description=manifest.description,
            model_profile=profile,
            allowed_tools=tuple(manifest.allowed_tools),
            output_schema=schema,
            instructions=(skill_dir / "SKILL.md").read_text("utf-8"),
            examples=tuple(examples),
            clarification_conditions=tuple(manifest.clarification_conditions),
            termination_conditions=tuple(manifest.termination_conditions),
            acceptance_rules=tuple(manifest.acceptance_rules),
        )


class SkillRegistry:
    def __init__(self, trace_writer: TraceWriter) -> None:
        self._skills: dict[str, LoadedSkill] = {}
        self._traces = trace_writer

    def register(self, skill: LoadedSkill) -> None:
        if skill.name in self._skills:
            raise ProjectError(
                ErrorCode.ALREADY_EXISTS,
                f"Skill already registered: {skill.name}",
            )
        self._skills[skill.name] = skill

    def load_all(self, loader: SkillManifestLoader) -> None:
        for skill in loader.discover():
            self.register(skill)

    def get(self, name: str) -> LoadedSkill | None:
        return self._skills.get(name)

    def list_all(self) -> list[LoadedSkill]:
        return list(self._skills.values())

    async def activate(self, name: str, trace_id: str) -> LoadedSkill:
        skill = self.get(name)
        if skill is None:
            raise ProjectError(ErrorCode.SKILL_NOT_FOUND, f"Skill not found: {name}")
        await self._traces.write_trace(
            trace_id,
            "skill.activate",
            {
                "skill_name": skill.name,
                "skill_version": skill.version,
                "model_profile": skill.model_profile,
                "allowed_tools": list(skill.allowed_tools),
            },
        )
        return skill


def _validate_json_schema(value: Any, schema: dict[str, Any], path: str = "$") -> None:
    expected = schema.get("type")
    type_map: dict[str, type | tuple[type, ...]] = {
        "object": dict,
        "array": list,
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
    }
    if expected in type_map and not isinstance(value, type_map[expected]):
        raise ValueError(f"Schema validation failed at {path}: expected {expected}")
    if expected == "object":
        required = set(schema.get("required", []))
        missing = required - set(value)
        if missing:
            raise ValueError(f"Schema validation failed at {path}: missing {sorted(missing)}")
        for key, child_schema in schema.get("properties", {}).items():
            if key in value:
                _validate_json_schema(value[key], child_schema, f"{path}.{key}")
    if expected == "array" and "items" in schema:
        for index, item in enumerate(value):
            _validate_json_schema(item, schema["items"], f"{path}[{index}]")
