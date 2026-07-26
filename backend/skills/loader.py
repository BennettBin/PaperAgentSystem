import importlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.core.errors import ErrorCode, ProjectError
from backend.core.ports.observability import TraceWriter


class SkillManifestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    description: str = Field(min_length=1)
    model_profile: str = Field(min_length=1)
    input_contract: "StructuredContractModel"
    output_contract: "StructuredContractModel"
    trigger_conditions: list[str] = Field(min_length=1)
    non_trigger_conditions: list[str] = Field(min_length=1)
    routing_keywords: list[str] = Field(min_length=1)
    clarification_conditions: list[str] = Field(min_length=1)
    termination_conditions: list[str] = Field(min_length=1)
    acceptance_rules: list[str] = Field(min_length=1)
    routing_policy: "SkillRoutingPolicyModel" = Field(
        default_factory=lambda: SkillRoutingPolicyModel()
    )
    input_policy: "SkillInputPolicyModel | None" = None


class SkillRoutingPolicyModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_files: int = Field(default=0, ge=0)
    max_files: int | None = Field(default=None, ge=1)
    exclusive: bool = False
    runs_after: list[str] = Field(default_factory=list)


class SkillInputPolicyModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accepted_sources: list[Literal["inline_text", "conversation_material", "uploaded_files", "external"]] = Field(default_factory=list)
    source_required: bool = False
    min_files: int = Field(default=0, ge=0)
    max_files: int | None = Field(default=None, ge=1)
    memory_policy: Literal["none", "constraints_only", "specific_material", "recent_context", "cross_conversation"] = "none"
    missing_source_prompt: str = "请提供完成该任务所需的材料。"


@dataclass(frozen=True)
class SkillRoutingPolicy:
    min_files: int
    max_files: int | None
    exclusive: bool
    runs_after: tuple[str, ...]


@dataclass(frozen=True)
class SkillInputPolicy:
    accepted_sources: tuple[str, ...]
    source_required: bool
    min_files: int
    max_files: int | None
    memory_policy: str
    missing_source_prompt: str


@dataclass(frozen=True)
class LoadedSkill:
    name: str
    version: str
    description: str
    model_profile: str
    input_contract: "StructuredContract"
    output_contract: "StructuredContract"
    tools: tuple["SkillToolBinding", ...]
    instructions: str
    examples: tuple[dict[str, Any], ...]
    trigger_conditions: tuple[str, ...]
    non_trigger_conditions: tuple[str, ...]
    routing_keywords: tuple[str, ...]
    clarification_conditions: tuple[str, ...]
    termination_conditions: tuple[str, ...]
    acceptance_rules: tuple[str, ...]
    routing_policy: SkillRoutingPolicy
    input_policy: SkillInputPolicy

    @property
    def allowed_tools(self) -> tuple[str, ...]:
        return tuple(tool.name for tool in self.tools)

    @property
    def input_schema(self) -> dict[str, Any]:
        return self.input_contract.schema or {}

    @property
    def output_schema(self) -> dict[str, Any]:
        return self.output_contract.schema or {}


class StructuredContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    format: Literal["object", "markdown", "markdown_table"]
    schema_path: str | None = Field(default=None, alias="schema")
    min_length: int = Field(default=1, ge=1)
    required_markers: list[str] = Field(default_factory=list)
    required_columns: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class StructuredContract:
    format: str
    schema: dict[str, Any] | None
    min_length: int
    required_markers: tuple[str, ...]
    required_columns: tuple[str, ...]


class SkillToolBindingModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    when_to_use: str = Field(min_length=1)
    implementation: str = Field(min_length=1)
    example_input: dict[str, Any]


class SkillToolsModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tools: list[SkillToolBindingModel] = Field(min_length=1)


@dataclass(frozen=True)
class SkillToolBinding:
    name: str
    purpose: str
    when_to_use: str
    implementation: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    example_input: dict[str, Any]


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
        required_files = ("manifest.yaml", "SKILL.md", "examples.json", "tools/tools.yaml")
        missing_files = [name for name in required_files if not (skill_dir / name).is_file()]
        if missing_files:
            raise ValueError(f"Missing Skill files: {missing_files}")
        raw = yaml.safe_load((skill_dir / "manifest.yaml").read_text("utf-8"))
        try:
            manifest = SkillManifestModel.model_validate(raw)
        except ValidationError as exc:
            raise ValueError(f"Invalid Skill manifest: {exc}") from exc
        raw_tools = yaml.safe_load((skill_dir / "tools" / "tools.yaml").read_text("utf-8"))
        try:
            tool_models = SkillToolsModel.model_validate(raw_tools).tools
        except ValidationError as exc:
            raise ValueError(f"Invalid Skill Tool bindings: {exc}") from exc
        names = [tool.name for tool in tool_models]
        if len(names) != len(set(names)):
            raise ValueError(f"Duplicate Skill Tool binding in {skill_dir.name}")
        missing_tools = set(names) - self.registered_tools
        if missing_tools:
            raise ValueError(f"Unregistered tools: {sorted(missing_tools)}")
        profile = manifest.model_profile
        if profile not in self.available_profiles:
            profile = self.fallback_profile
        if "/" in profile or "\\" in profile:
            raise ValueError("Skill model_profile must not contain a physical path")
        input_contract = _load_contract(skill_dir, manifest.input_contract)
        output_contract = _load_contract(skill_dir, manifest.output_contract)
        tools = tuple(_load_tool_binding(tool) for tool in tool_models)
        for tool in tools:
            try:
                tool.input_model.model_validate(tool.example_input)
            except ValidationError as exc:
                raise ValueError(
                    f"Invalid example input for Tool {tool.name}: {exc}"
                ) from exc
        examples = json.loads((skill_dir / "examples.json").read_text("utf-8"))
        if not isinstance(examples, list) or not examples:
            raise ValueError("Skill examples.json must contain at least one example")
        for example in examples:
            if not isinstance(example, dict) or "input" not in example or "output" not in example:
                raise ValueError("Each Skill example requires input and output")
            _validate_structured_value(example["input"], input_contract)
            _validate_structured_value(example["output"], output_contract)
        input_policy = manifest.input_policy or SkillInputPolicyModel(
            accepted_sources=(
                ["uploaded_files"] if manifest.routing_policy.min_files else []
            ),
            source_required=manifest.routing_policy.min_files > 0,
            min_files=manifest.routing_policy.min_files,
            max_files=manifest.routing_policy.max_files,
            missing_source_prompt="请上传或选择完成该任务所需的论文。",
        )
        return LoadedSkill(
            name=manifest.name,
            version=manifest.version,
            description=manifest.description,
            model_profile=profile,
            input_contract=input_contract,
            output_contract=output_contract,
            tools=tools,
            instructions=(skill_dir / "SKILL.md").read_text("utf-8"),
            examples=tuple(examples),
            trigger_conditions=tuple(manifest.trigger_conditions),
            non_trigger_conditions=tuple(manifest.non_trigger_conditions),
            routing_keywords=tuple(manifest.routing_keywords),
            clarification_conditions=tuple(manifest.clarification_conditions),
            termination_conditions=tuple(manifest.termination_conditions),
            acceptance_rules=tuple(manifest.acceptance_rules),
            routing_policy=SkillRoutingPolicy(
                min_files=manifest.routing_policy.min_files,
                max_files=manifest.routing_policy.max_files,
                exclusive=manifest.routing_policy.exclusive,
                runs_after=tuple(manifest.routing_policy.runs_after),
            ),
            input_policy=SkillInputPolicy(
                accepted_sources=tuple(input_policy.accepted_sources),
                source_required=input_policy.source_required,
                min_files=input_policy.min_files,
                max_files=input_policy.max_files,
                memory_policy=input_policy.memory_policy,
                missing_source_prompt=input_policy.missing_source_prompt,
            ),
        )


def _load_contract(
    skill_dir: Path, model: StructuredContractModel
) -> StructuredContract:
    schema = None
    if model.format == "object":
        if not model.schema_path:
            raise ValueError("Object Skill contract requires a schema")
        schema_path = skill_dir / model.schema_path
        if not schema_path.is_file():
            raise ValueError(f"Missing Skill contract schema: {model.schema_path}")
        schema = json.loads(schema_path.read_text("utf-8"))
    elif model.schema_path:
        raise ValueError("Text Skill contract must not declare a JSON schema")
    if model.format == "markdown_table" and not model.required_columns:
        raise ValueError("Markdown table contract requires columns")
    return StructuredContract(
        format=model.format,
        schema=schema,
        min_length=model.min_length,
        required_markers=tuple(model.required_markers),
        required_columns=tuple(model.required_columns),
    )


def _load_tool_binding(model: SkillToolBindingModel) -> SkillToolBinding:
    module_name, separator, class_name = model.implementation.rpartition(".")
    if not separator:
        raise ValueError(f"Invalid Tool implementation: {model.implementation}")
    try:
        implementation = getattr(importlib.import_module(module_name), class_name)
        input_model = implementation.input_model
        output_model = implementation.output_model
    except (ImportError, AttributeError) as exc:
        raise ValueError(f"Unavailable Tool implementation: {model.implementation}") from exc
    if getattr(implementation, "name", None) != model.name:
        raise ValueError(
            f"Tool implementation name mismatch: {model.name} != "
            f"{getattr(implementation, 'name', None)}"
        )
    return SkillToolBinding(
        name=model.name,
        purpose=model.purpose,
        when_to_use=model.when_to_use,
        implementation=model.implementation,
        input_model=input_model,
        output_model=output_model,
        input_schema=input_model.model_json_schema(),
        output_schema=output_model.model_json_schema(),
        example_input=model.example_input,
    )


def _validate_structured_value(value: Any, contract: StructuredContract) -> None:
    if contract.format == "object":
        if contract.schema is None:
            raise ValueError("Object contract schema is unavailable")
        _validate_json_schema(value, contract.schema)
        return
    if not isinstance(value, str):
        raise ValueError(f"expected {contract.format} text")
    if len(value.strip()) < contract.min_length:
        raise ValueError(f"{contract.format} content is too short")
    missing_markers = [marker for marker in contract.required_markers if marker not in value]
    if missing_markers:
        raise ValueError(f"missing required markers: {missing_markers}")
    if contract.format == "markdown_table":
        header = next((line for line in value.splitlines() if line.strip().startswith("|")), "")
        missing_columns = [column for column in contract.required_columns if column not in header]
        if missing_columns:
            raise ValueError(f"missing table columns: {missing_columns}")


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

    async def trace_complete(
        self, skill: LoadedSkill, trace_id: str, status: str
    ) -> None:
        await self._traces.write_trace(
            trace_id,
            "skill.complete",
            {
                "skill_name": skill.name,
                "skill_version": skill.version,
                "status": status,
            },
        )

    async def trace_tool(
        self,
        trace_id: str,
        span_name: str,
        data: dict[str, Any],
        *,
        error: str | None = None,
    ) -> None:
        await self._traces.write_trace(trace_id, span_name, data, error=error)


def _validate_json_schema(value: Any, schema: dict[str, Any], path: str = "$") -> None:
    expected = schema.get("type")
    type_map: dict[str, tuple[type, ...]] = {
        "object": (dict,),
        "array": (list,),
        "string": (str,),
        "integer": (int,),
        "number": (int, float),
        "boolean": (bool,),
    }
    expected_types = expected if isinstance(expected, list) else [expected]
    allowed_python_types = tuple(
        python_type
        for item in expected_types
        for python_type in (
            type_map[item]
            if item in type_map
            else ((type(None),) if item == "null" else ())
        )
    )
    if allowed_python_types and not isinstance(value, allowed_python_types):
        raise ValueError(f"Schema validation failed at {path}: expected {expected}")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"Schema validation failed at {path}: value is not allowed")
    if expected == "object":
        required = set(schema.get("required", []))
        missing = required - set(value)
        if missing:
            raise ValueError(f"Schema validation failed at {path}: missing {sorted(missing)}")
        if schema.get("additionalProperties") is False:
            unexpected = set(value) - set(schema.get("properties", {}))
            if unexpected:
                raise ValueError(
                    f"Schema validation failed at {path}: unexpected {sorted(unexpected)}"
                )
        for key, child_schema in schema.get("properties", {}).items():
            if key in value:
                _validate_json_schema(value[key], child_schema, f"{path}.{key}")
    if expected == "array" and "items" in schema:
        for index, item in enumerate(value):
            _validate_json_schema(item, schema["items"], f"{path}[{index}]")
