"""Workspace-scoped Tool definitions."""

from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from tool_runtime.runtime import ToolContext, ToolDefinition, ToolPolicy, ToolRegistry
from workspace.search import WorkspaceSearchService
from workspace.service import WorkspaceEntry, WorkspaceService


class EmptyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EntryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_entry_id: str = Field(min_length=1)


class WriteEntryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    relative_path: str = Field(min_length=1)
    content: str
    content_type: str = "text/plain"


class SearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1)
    limit: int = Field(default=5, ge=1, le=20)


class PromoteInput(EntryInput):
    destination: str = Field(default="shared", pattern=r"^(shared|artifacts)$")


class SaveArtifactInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filename: str = Field(min_length=1, pattern=r"^[^/\\]+$")
    content: str
    content_type: str = "text/markdown"


class EntryRecord(BaseModel):
    workspace_entry_id: str
    relative_path: str
    content_type: str
    task_id: str | None
    object_key: str | None
    source_type: str
    source_id: str | None


class EntryListOutput(BaseModel):
    entries: list[EntryRecord]


class EntryContentOutput(BaseModel):
    entry: EntryRecord
    content: str


class SearchOutput(BaseModel):
    entries: list[EntryRecord]


class EntryOutput(BaseModel):
    entry: EntryRecord


class AuditWriter(Protocol):
    async def record(self, event: dict[str, str]) -> None: ...


@dataclass
class InMemoryWorkspaceAuditWriter:
    events: list[dict[str, str]]

    def __init__(self) -> None:
        self.events = []

    async def record(self, event: dict[str, str]) -> None:
        self.events.append(event)


def _record(entry: WorkspaceEntry) -> EntryRecord:
    return EntryRecord(
        workspace_entry_id=entry.entry_id,
        relative_path=entry.relative_path,
        content_type=entry.content_type,
        task_id=entry.task_id,
        object_key=entry.object_key,
        source_type=entry.source_type,
        source_id=entry.source_id,
    )


class ListWorkspaceFiles(ToolDefinition[EmptyInput, EntryListOutput]):
    name = "list_workspace_files"
    description = "List entries in the current conversation and task scope."
    input_model = EmptyInput
    output_model = EntryListOutput
    policy = ToolPolicy(permission="workspace:read")

    def __init__(self, workspace: WorkspaceService) -> None:
        self._workspace = workspace

    async def execute(self, context: ToolContext, arguments: EmptyInput) -> EntryListOutput:
        entries = self._workspace.list_entries(
            context.workspace_id,
            context.conversation_id,
            task_id=context.task_id,
        )
        return EntryListOutput(entries=[_record(entry) for entry in entries])


class SearchWorkspaceFiles(ToolDefinition[SearchInput, SearchOutput]):
    name = "search_workspace_files"
    description = "Search Workspace entries by indexed content."
    input_model = SearchInput
    output_model = SearchOutput
    policy = ToolPolicy(permission="workspace:read")

    def __init__(
        self,
        workspace: WorkspaceService,
        search: WorkspaceSearchService,
    ) -> None:
        self._workspace = workspace
        self._search = search

    async def execute(self, context: ToolContext, arguments: SearchInput) -> SearchOutput:
        results = await self._search.search(
            context.workspace_id,
            arguments.query,
            current_conversation_id=context.conversation_id,
            current_task_id=context.task_id,
            limit=arguments.limit,
        )
        entries = []
        for result in results:
            if result.conversation_id != context.conversation_id:
                continue
            entry = self._workspace.get_entry(
                result.entry_id,
                context.workspace_id,
                context.conversation_id,
                task_id=context.task_id,
            )
            entries.append(_record(entry))
        return SearchOutput(entries=entries)


class ReadWorkspaceEntry(ToolDefinition[EntryInput, EntryContentOutput]):
    name = "read_workspace_entry"
    description = "Read one entry assigned to the current task scope."
    input_model = EntryInput
    output_model = EntryContentOutput
    policy = ToolPolicy(permission="workspace:read")

    def __init__(self, workspace: WorkspaceService) -> None:
        self._workspace = workspace

    async def execute(self, context: ToolContext, arguments: EntryInput) -> EntryContentOutput:
        entry = self._workspace.get_entry(
            arguments.workspace_entry_id,
            context.workspace_id,
            context.conversation_id,
            task_id=context.task_id,
        )
        content = self._workspace.read_entry(
            entry.entry_id,
            context.workspace_id,
            context.conversation_id,
            entry.task_id,
        )
        return EntryContentOutput(entry=_record(entry), content=content.decode("utf-8"))


class WriteWorkspaceEntry(ToolDefinition[WriteEntryInput, EntryOutput]):
    name = "write_workspace_entry"
    description = "Write a non-executable entry into the current TaskWorkspace."
    input_model = WriteEntryInput
    output_model = EntryOutput
    policy = ToolPolicy(permission="workspace:write", side_effect="write")

    def __init__(self, workspace: WorkspaceService) -> None:
        self._workspace = workspace

    async def execute(self, context: ToolContext, arguments: WriteEntryInput) -> EntryOutput:
        entry = await self._workspace.write_entry(
            context.workspace_id,
            context.conversation_id,
            arguments.relative_path,
            arguments.content.encode("utf-8"),
            arguments.content_type,
            task_id=context.task_id,
            source_type="tool",
            source_id=self.name,
        )
        return EntryOutput(entry=_record(entry))


class PromoteWorkspaceEntry(ToolDefinition[PromoteInput, EntryOutput]):
    name = "promote_workspace_entry"
    description = "Promote a task entry to shared or artifacts with an audit event."
    input_model = PromoteInput
    output_model = EntryOutput
    policy = ToolPolicy(permission="workspace:promote", side_effect="write")

    def __init__(self, workspace: WorkspaceService, audit: AuditWriter) -> None:
        self._workspace = workspace
        self._audit = audit

    async def execute(self, context: ToolContext, arguments: PromoteInput) -> EntryOutput:
        self._workspace.get_entry(
            arguments.workspace_entry_id,
            context.workspace_id,
            context.conversation_id,
            task_id=context.task_id,
        )
        promoted = self._workspace.promote(
            arguments.workspace_entry_id,
            context.workspace_id,
            arguments.destination,
        )
        await self._audit.record(
            {
                "action": "workspace.promote",
                "workspace_id": context.workspace_id,
                "task_id": context.task_id,
                "source_entry_id": arguments.workspace_entry_id,
                "promoted_entry_id": promoted.entry_id,
                "destination": arguments.destination,
            }
        )
        return EntryOutput(entry=_record(promoted))


class SaveArtifact(ToolDefinition[SaveArtifactInput, EntryOutput]):
    name = "save_artifact"
    description = "Save a durable user-managed artifact."
    input_model = SaveArtifactInput
    output_model = EntryOutput
    policy = ToolPolicy(permission="workspace:write", side_effect="write")

    def __init__(self, workspace: WorkspaceService) -> None:
        self._workspace = workspace

    async def execute(self, context: ToolContext, arguments: SaveArtifactInput) -> EntryOutput:
        entry = await self._workspace.write_entry(
            context.workspace_id,
            context.conversation_id,
            f"artifacts/{arguments.filename}",
            arguments.content.encode("utf-8"),
            arguments.content_type,
            retention="permanent",
            source_type="tool",
            source_id=self.name,
        )
        return EntryOutput(entry=_record(entry))


def register_workspace_tools(
    registry: ToolRegistry,
    workspace: WorkspaceService,
    search: WorkspaceSearchService,
    audit: AuditWriter,
) -> None:
    for tool in (
        ListWorkspaceFiles(workspace),
        SearchWorkspaceFiles(workspace, search),
        ReadWorkspaceEntry(workspace),
        WriteWorkspaceEntry(workspace),
        PromoteWorkspaceEntry(workspace, audit),
        SaveArtifact(workspace),
    ):
        registry.register(tool)
