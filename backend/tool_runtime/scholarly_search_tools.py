"""Atomic read-only tools for topic-based scholarly metadata discovery."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.core.ports.scholarly import ScholarlySearchPage, ScholarlySearchProvider
from backend.tool_runtime.runtime import ToolContext, ToolDefinition, ToolPolicy, ToolRegistry


class ScholarlySearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=2, max_length=500)
    limit: int = Field(default=5, ge=1, le=20)
    year_from: int | None = Field(default=None, ge=1900)
    year_to: int | None = Field(default=None, ge=1900)

    @model_validator(mode="after")
    def validate_years(self) -> "ScholarlySearchInput":
        current_year = datetime.now(UTC).year + 1
        if self.year_from is not None and self.year_from > current_year:
            raise ValueError("year_from is outside the supported range")
        if self.year_to is not None and self.year_to > current_year:
            raise ValueError("year_to is outside the supported range")
        if (
            self.year_from is not None
            and self.year_to is not None
            and self.year_from > self.year_to
        ):
            raise ValueError("year_from must not exceed year_to")
        return self


class ScholarlyWorkOutput(BaseModel):
    source: str
    external_id: str
    title: str
    abstract: str | None = None
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    doi: str | None = None
    url: str | None = None
    citation_count: int | None = None
    open_access_url: str | None = None


class ScholarlySearchOutput(BaseModel):
    source: str
    query: str
    total: int | None = None
    works: list[ScholarlyWorkOutput]


class _ScholarlySearchTool(ToolDefinition[ScholarlySearchInput, ScholarlySearchOutput]):
    input_model = ScholarlySearchInput
    output_model = ScholarlySearchOutput
    policy = ToolPolicy(permission="external:read", timeout_seconds=20)

    def __init__(self, provider: ScholarlySearchProvider) -> None:
        self._provider = provider

    async def execute(
        self,
        context: ToolContext,
        arguments: ScholarlySearchInput,
    ) -> ScholarlySearchOutput:
        del context
        page = await self._provider.search(
            arguments.query,
            limit=arguments.limit,
            year_from=arguments.year_from,
            year_to=arguments.year_to,
        )
        return _to_output(page)


class CrossrefSearchTool(_ScholarlySearchTool):
    name = "search_crossref"
    description = "Search Crossref for papers and DOI metadata by topic."


class SemanticScholarSearchTool(_ScholarlySearchTool):
    name = "search_semantic_scholar"
    description = "Search Semantic Scholar for papers and citation metadata by topic."


class OpenAlexSearchTool(_ScholarlySearchTool):
    name = "search_openalex"
    description = "Search OpenAlex for papers and open scholarly metadata by topic."


class ArxivSearchTool(_ScholarlySearchTool):
    name = "search_arxiv"
    description = "Search arXiv for preprints by topic."


def register_scholarly_search_tools(
    registry: ToolRegistry,
    *,
    crossref: ScholarlySearchProvider,
    semantic_scholar: ScholarlySearchProvider,
    openalex: ScholarlySearchProvider,
    arxiv: ScholarlySearchProvider,
) -> None:
    for tool in (
        CrossrefSearchTool(crossref),
        SemanticScholarSearchTool(semantic_scholar),
        OpenAlexSearchTool(openalex),
        ArxivSearchTool(arxiv),
    ):
        registry.register(tool)


def _to_output(page: ScholarlySearchPage) -> ScholarlySearchOutput:
    return ScholarlySearchOutput(
        source=page.source,
        query=page.query,
        total=page.total,
        works=[
            ScholarlyWorkOutput(
                source=work.source,
                external_id=work.external_id,
                title=work.title,
                abstract=work.abstract,
                authors=list(work.authors),
                year=work.year,
                venue=work.venue,
                doi=work.doi,
                url=work.url,
                citation_count=work.citation_count,
                open_access_url=work.open_access_url,
            )
            for work in page.works
        ],
    )
