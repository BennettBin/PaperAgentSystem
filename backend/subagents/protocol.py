"""Strict role manifests and reference-only multi-Agent messaging protocol."""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.core.errors import ErrorCode, ProjectError


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AgentRole(StrEnum):
    COORDINATOR = "coordinator"
    PAPER_READER = "paper_reader"
    EVIDENCE = "evidence"
    CRITIC = "critic"
    WRITER = "writer"
    VERIFIER = "verifier"


class MessageType(StrEnum):
    REQUEST = "request"
    RESULT = "result"
    FAILURE = "failure"
    CANCEL = "cancel"


class RoleBudget(_StrictModel):
    max_tokens: int = Field(ge=0)
    max_steps: int = Field(ge=1, le=8)
    max_tool_calls: int = Field(ge=0)
    timeout_seconds: int = Field(gt=0)
    max_retries: int = Field(default=1, ge=0, le=2)


class RoleFailurePolicy(_StrictModel):
    required: bool
    on_unavailable: Literal["degrade", "fail"]
    on_timeout: Literal["retry_once", "degrade", "fail"]


class RoleManifest(_StrictModel):
    name: str = Field(min_length=1)
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    role: AgentRole
    description: str = Field(min_length=1)
    model_profile: str = Field(min_length=1)
    allowed_tools: list[str] = Field(default_factory=list)
    input_schema: str = Field(min_length=1)
    output_schema: str = Field(min_length=1)
    budget: RoleBudget
    stop_conditions: list[str] = Field(min_length=1)
    failure_policy: RoleFailurePolicy
    max_depth: Literal[1] = 1
    can_message_user: Literal[False] = False
    can_spawn_agents: Literal[False] = False
    example_input: dict[str, Any]
    example_output: dict[str, Any]

    @model_validator(mode="after")
    def name_matches_role(self) -> RoleManifest:
        if self.name != f"{self.role.value}_agent":
            raise ValueError("Role Manifest name must be '<role>_agent'")
        if len(self.allowed_tools) != len(set(self.allowed_tools)):
            raise ValueError("Role Tool whitelist contains duplicates")
        return self


class ArtifactRef(_StrictModel):
    artifact_id: str = Field(min_length=1)
    artifact_type: str = Field(min_length=1)
    owner: AgentRole
    version: int = Field(ge=1)
    checksum: str | None = None


class DataRef(_StrictModel):
    uri: str = Field(pattern=r"^(workspace|artifact|blackboard)://")
    media_type: str = Field(min_length=1)
    checksum: str | None = None


class MessageEnvelope(_StrictModel):
    message_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    sender: AgentRole
    recipient: AgentRole
    message_type: MessageType
    artifact_refs: list[ArtifactRef] = Field(default_factory=list)
    data_refs: list[DataRef] = Field(default_factory=list)
    schema_name: str = Field(min_length=1)
    schema_version: str = Field(min_length=1)
    attempt: int = Field(default=1, ge=1, le=2)
    deadline_epoch_ms: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def enforce_reference_only_routing(self) -> MessageEnvelope:
        if self.sender is self.recipient:
            raise ValueError("Agent messages must cross role boundaries")
        if (
            self.message_type in {MessageType.REQUEST, MessageType.RESULT}
            and not self.artifact_refs
            and not self.data_refs
        ):
            raise ValueError("Request/result messages require an ArtifactRef or DataRef")
        return self


class CoordinationDecision(_StrictModel):
    status: Literal["ready", "degraded", "failed"]
    missing_required_roles: list[AgentRole] = Field(default_factory=list)
    skipped_roles: list[AgentRole] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    public_reason: str


class RoleProtocolRegistry:
    def __init__(
        self,
        manifests: dict[AgentRole, RoleManifest],
        input_schemas: dict[AgentRole, dict[str, Any]],
        output_schemas: dict[AgentRole, dict[str, Any]],
    ) -> None:
        self.manifests = manifests
        self._inputs = input_schemas
        self._outputs = output_schemas

    @classmethod
    def load(cls, root: Path) -> RoleProtocolRegistry:
        resolved_root = root.resolve()
        manifests: dict[AgentRole, RoleManifest] = {}
        inputs: dict[AgentRole, dict[str, Any]] = {}
        outputs: dict[AgentRole, dict[str, Any]] = {}
        for path in sorted(root.glob("*.yaml")):
            manifest = RoleManifest.model_validate(
                yaml.safe_load(path.read_text("utf-8"))
            )
            if manifest.role in manifests:
                raise ValueError(f"Duplicate role Manifest: {manifest.role.value}")
            input_path = _contained(resolved_root, root / manifest.input_schema)
            output_path = _contained(resolved_root, root / manifest.output_schema)
            input_schema = _load_schema(input_path)
            output_schema = _load_schema(output_path)
            _validate(instance=manifest.example_input, schema=input_schema, path="input")
            _validate(instance=manifest.example_output, schema=output_schema, path="output")
            manifests[manifest.role] = manifest
            inputs[manifest.role] = input_schema
            outputs[manifest.role] = output_schema
        missing = set(AgentRole) - set(manifests)
        extra = set(manifests) - set(AgentRole)
        if missing or extra:
            raise ValueError(
                f"Role Manifest set mismatch: missing={sorted(item.value for item in missing)}"
            )
        return cls(manifests, inputs, outputs)

    def validate_input(self, role: AgentRole, value: dict[str, Any]) -> None:
        _validate(instance=value, schema=self._inputs[role], path=f"{role.value}.input")

    def validate_output(self, role: AgentRole, value: dict[str, Any]) -> None:
        _validate(instance=value, schema=self._outputs[role], path=f"{role.value}.output")

    def example_input(self, role: AgentRole) -> dict[str, Any]:
        return dict(self.manifests[role].example_input)

    def example_output(self, role: AgentRole) -> dict[str, Any]:
        return dict(self.manifests[role].example_output)

    def authorize_tool(self, role: AgentRole, tool_name: str) -> None:
        if tool_name not in self.manifests[role].allowed_tools:
            raise ProjectError(
                ErrorCode.PERMISSION_DENIED,
                "Role is not permitted to invoke Tool",
                {"role": role.value, "tool": tool_name},
            )


class CoordinatorDegradationPolicy:
    def __init__(self, registry: RoleProtocolRegistry) -> None:
        self._registry = registry

    def decide(
        self,
        *,
        available_roles: set[AgentRole],
        failed_roles: set[AgentRole],
    ) -> CoordinationDecision:
        unavailable = (set(AgentRole) - available_roles) | failed_roles
        missing_required = sorted(
            (
                role
                for role in unavailable
                if self._registry.manifests[role].failure_policy.required
                or self._registry.manifests[role].failure_policy.on_unavailable == "fail"
            ),
            key=lambda role: role.value,
        )
        if missing_required:
            return CoordinationDecision(
                status="failed",
                missing_required_roles=missing_required,
                public_reason=(
                    "Required collaboration roles are unavailable: "
                    + ", ".join(role.value for role in missing_required)
                ),
            )
        skipped = sorted(unavailable, key=lambda role: role.value)
        if skipped:
            return CoordinationDecision(
                status="degraded",
                skipped_roles=skipped,
                actions=[f"skip_optional_{role.value}" for role in skipped],
                public_reason=(
                    "Optional roles are unavailable; continue with labelled degraded output."
                ),
            )
        return CoordinationDecision(
            status="ready",
            public_reason="All required collaboration roles are available.",
        )


def _contained(root: Path, path: Path) -> Path:
    resolved = path.resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError("Role schema path escapes role root")
    return resolved


def _load_schema(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text("utf-8"))
    if not isinstance(payload, dict) or payload.get("type") != "object":
        raise ValueError(f"Role schema must be an object schema: {path.name}")
    if not isinstance(payload.get("properties"), dict):
        raise ValueError(f"Role schema requires properties: {path.name}")
    return payload


def _validate(*, instance: Any, schema: dict[str, Any], path: str) -> None:
    expected = schema.get("type")
    type_checks = {
        "object": lambda value: isinstance(value, dict),
        "array": lambda value: isinstance(value, list),
        "string": lambda value: isinstance(value, str),
        "integer": lambda value: isinstance(value, int) and not isinstance(value, bool),
        "number": lambda value: isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": lambda value: isinstance(value, bool),
    }
    if expected in type_checks and not type_checks[expected](instance):
        raise ValueError(f"{path} must be {expected}")
    if "enum" in schema and instance not in schema["enum"]:
        raise ValueError(f"{path} is not an allowed enum value")
    if expected == "object":
        assert isinstance(instance, dict)
        properties = schema.get("properties", {})
        missing = set(schema.get("required", [])) - set(instance)
        if missing:
            raise ValueError(f"{path} missing fields: {sorted(missing)}")
        if schema.get("additionalProperties") is False:
            extra = set(instance) - set(properties)
            if extra:
                raise ValueError(f"{path} has extra fields: {sorted(extra)}")
        for name, value in instance.items():
            if name in properties:
                _validate(instance=value, schema=properties[name], path=f"{path}.{name}")
    elif expected == "array":
        assert isinstance(instance, list)
        if len(instance) < int(schema.get("minItems", 0)):
            raise ValueError(f"{path} contains too few items")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, value in enumerate(instance):
                _validate(instance=value, schema=item_schema, path=f"{path}[{index}]")
    elif expected == "string" and len(instance) < int(schema.get("minLength", 0)):
        raise ValueError(f"{path} is too short")
