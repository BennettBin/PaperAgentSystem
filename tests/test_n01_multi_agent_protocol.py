from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.core.errors import ErrorCode, ProjectError
from backend.subagents.protocol import (
    AgentRole,
    ArtifactRef,
    CoordinatorDegradationPolicy,
    DataRef,
    MessageEnvelope,
    MessageType,
    RoleProtocolRegistry,
)

ROLES_ROOT = Path("backend/subagents/roles")


def test_all_six_role_manifests_and_schemas_load_independently() -> None:
    registry = RoleProtocolRegistry.load(ROLES_ROOT)
    assert set(registry.manifests) == set(AgentRole)
    for role, manifest in registry.manifests.items():
        assert manifest.role is role
        assert manifest.max_depth == 1
        assert not manifest.can_message_user
        assert not manifest.can_spawn_agents
        assert manifest.stop_conditions
        registry.validate_input(role, registry.example_input(role))
        registry.validate_output(role, registry.example_output(role))


def test_message_envelope_allows_only_structured_refs_and_rejects_hidden_reasoning() -> None:
    envelope = MessageEnvelope(
        message_id="msg-1",
        task_id="task-1",
        workspace_id="ws-1",
        sender=AgentRole.COORDINATOR,
        recipient=AgentRole.PAPER_READER,
        message_type=MessageType.REQUEST,
        artifact_refs=[
            ArtifactRef(
                artifact_id="assignment-1",
                artifact_type="paper_assignment",
                owner=AgentRole.COORDINATOR,
                version=1,
            )
        ],
        data_refs=[DataRef(uri="workspace://ws-1/files/paper-1", media_type="application/pdf")],
        schema_name="paper_reader_input",
        schema_version="1.0",
    )
    assert envelope.artifact_refs[0].owner is AgentRole.COORDINATOR
    with pytest.raises(ValidationError):
        MessageEnvelope.model_validate(
            {**envelope.model_dump(mode="json"), "hidden_reasoning": "private CoT"}
        )
    with pytest.raises(ValidationError):
        MessageEnvelope.model_validate(
            {**envelope.model_dump(mode="json"), "payload": {"raw_text": "inline"}}
        )


def test_role_tool_whitelists_fail_closed_for_every_role() -> None:
    registry = RoleProtocolRegistry.load(ROLES_ROOT)
    denied = 0
    for role, manifest in registry.manifests.items():
        for tool in manifest.allowed_tools:
            registry.authorize_tool(role, tool)
        with pytest.raises(ProjectError) as exc:
            registry.authorize_tool(role, "cross_workspace_read")
        assert exc.value.code is ErrorCode.PERMISSION_DENIED
        denied += 1
    assert denied == len(AgentRole)


def test_coordinator_degrades_optional_critic_and_fails_for_required_roles() -> None:
    registry = RoleProtocolRegistry.load(ROLES_ROOT)
    policy = CoordinatorDegradationPolicy(registry)
    degraded = policy.decide(
        available_roles=set(AgentRole) - {AgentRole.CRITIC},
        failed_roles={AgentRole.CRITIC},
    )
    assert degraded.status == "degraded"
    assert degraded.skipped_roles == [AgentRole.CRITIC]
    assert "skip_optional_critic" in degraded.actions

    failed = policy.decide(
        available_roles=set(AgentRole) - {AgentRole.VERIFIER},
        failed_roles={AgentRole.VERIFIER},
    )
    assert failed.status == "failed"
    assert failed.missing_required_roles == [AgentRole.VERIFIER]
    assert failed.public_reason


def test_protocol_document_covers_required_operational_semantics() -> None:
    text = Path("backend/subagents/PROTOCOL.md").read_text("utf-8").casefold()
    for term in ("data ownership", "conflict", "timeout", "cancellation", "retry"):
        assert term in text
