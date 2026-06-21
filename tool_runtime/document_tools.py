"""Tool Runtime adapters for parsing and document retrieval."""

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from document_processing.schema import ParsedDocument
from infrastructure.postgres.models import DocumentChunkModel
from rag.indexing import DocumentIndexer
from rag.retrieval import HybridRetriever
from tool_runtime.runtime import ToolContext, ToolDefinition, ToolPolicy, ToolRegistry
from workspace.service import WorkspaceService


class ParsingPipeline(Protocol):
    async def parse(
        self,
        file_data: bytes,
        filename: str,
        *,
        trace_id: str,
    ) -> ParsedDocument: ...


class ParseDocumentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_entry_id: str = Field(min_length=1)


class ParseDocumentOutput(BaseModel):
    document_id: str
    file_id: str
    page_count: int
    section_titles: list[str]
    quality_score: float
    warnings: list[str]


class SearchDocumentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1)
    file_ids: list[str] = Field(min_length=1)
    limit: int = Field(default=8, ge=1, le=8)


class SearchHitOutput(BaseModel):
    chunk_id: str
    file_id: str
    text: str
    section_path: list[str]
    page_start: int
    page_end: int
    bbox: tuple[float, float, float, float]
    score: float


class SearchDocumentOutput(BaseModel):
    hits: list[SearchHitOutput]


class GetDocumentSectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    file_id: str = Field(min_length=1)
    section_title: str = Field(min_length=1)


class GetDocumentSectionOutput(BaseModel):
    file_id: str
    section_title: str
    chunks: list[SearchHitOutput]


class ParseDocumentTool(ToolDefinition[ParseDocumentInput, ParseDocumentOutput]):
    name = "parse_document"
    description = "Parse and index one Workspace PDF entry."
    input_model = ParseDocumentInput
    output_model = ParseDocumentOutput
    policy = ToolPolicy(permission="workspace:read", timeout_seconds=180)

    def __init__(
        self,
        workspace: WorkspaceService,
        parser: ParsingPipeline,
        indexer: DocumentIndexer,
    ) -> None:
        self._workspace = workspace
        self._parser = parser
        self._indexer = indexer

    async def execute(
        self,
        context: ToolContext,
        arguments: ParseDocumentInput,
    ) -> ParseDocumentOutput:
        entry = self._workspace.get_entry(
            arguments.workspace_entry_id,
            context.workspace_id,
            context.conversation_id,
            task_id=context.task_id,
        )
        data = self._workspace.read_entry(
            entry.entry_id,
            context.workspace_id,
            context.conversation_id,
            entry.task_id,
        )
        parsed = await self._parser.parse(
            data,
            entry.relative_path,
            trace_id=context.trace_id,
        )
        chunks = await self._indexer.index(
            context.workspace_id,
            entry.entry_id,
            data,
            parsed,
        )
        return ParseDocumentOutput(
            document_id=chunks[0].document_id,
            file_id=entry.entry_id,
            page_count=parsed.page_count,
            section_titles=[section.title for section in parsed.sections],
            quality_score=parsed.quality.score,
            warnings=parsed.quality.warnings,
        )


class SearchDocumentTool(ToolDefinition[SearchDocumentInput, SearchDocumentOutput]):
    name = "search_document"
    description = "Hybrid-search assigned files with traceable page evidence."
    input_model = SearchDocumentInput
    output_model = SearchDocumentOutput
    policy = ToolPolicy(permission="workspace:read")

    def __init__(self, retriever: HybridRetriever) -> None:
        self._retriever = retriever

    async def execute(
        self,
        context: ToolContext,
        arguments: SearchDocumentInput,
    ) -> SearchDocumentOutput:
        hits = await self._retriever.search(
            arguments.query,
            workspace_id=context.workspace_id,
            file_ids=set(arguments.file_ids),
            limit=arguments.limit,
        )
        return SearchDocumentOutput(
            hits=[
                SearchHitOutput(
                    chunk_id=hit.chunk_id,
                    file_id=hit.file_id,
                    text=hit.text,
                    section_path=list(hit.section_path),
                    page_start=hit.page_start,
                    page_end=hit.page_end,
                    bbox=hit.bbox,
                    score=hit.score,
                )
                for hit in hits
            ]
        )


class GetDocumentSectionTool(
    ToolDefinition[GetDocumentSectionInput, GetDocumentSectionOutput]
):
    name = "get_document_section"
    description = "Read one indexed section from an assigned file."
    input_model = GetDocumentSectionInput
    output_model = GetDocumentSectionOutput
    policy = ToolPolicy(permission="workspace:read")

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sessions = session_factory

    async def execute(
        self,
        context: ToolContext,
        arguments: GetDocumentSectionInput,
    ) -> GetDocumentSectionOutput:
        with self._sessions() as session:
            models = session.scalars(
                select(DocumentChunkModel).where(
                    DocumentChunkModel.workspace_id == context.workspace_id,
                    DocumentChunkModel.file_id == arguments.file_id,
                    DocumentChunkModel.level == "child",
                )
            ).all()
        selected = [
            model
            for model in models
            if arguments.section_title.casefold()
            in " / ".join(model.section_path).casefold()
        ]
        return GetDocumentSectionOutput(
            file_id=arguments.file_id,
            section_title=arguments.section_title,
            chunks=[
                SearchHitOutput(
                    chunk_id=model.id,
                    file_id=model.file_id,
                    text=model.text,
                    section_path=model.section_path,
                    page_start=model.page_start,
                    page_end=model.page_end,
                    bbox=(
                        model.bbox_json[0],
                        model.bbox_json[1],
                        model.bbox_json[2],
                        model.bbox_json[3],
                    ),
                    score=1.0,
                )
                for model in selected
            ],
        )


def register_document_tools(
    registry: ToolRegistry,
    workspace: WorkspaceService,
    parser: ParsingPipeline,
    indexer: DocumentIndexer,
    retriever: HybridRetriever,
    session_factory: sessionmaker[Session],
) -> None:
    for tool in (
        ParseDocumentTool(workspace, parser, indexer),
        SearchDocumentTool(retriever),
        GetDocumentSectionTool(session_factory),
    ):
        registry.register(tool)
