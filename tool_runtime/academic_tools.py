"""Typed Tool adapters for evidence-bounded academic tasks."""

from pydantic import BaseModel, ConfigDict, Field

from academic_tasks.comparison import (
    ComparisonResult,
    MultiPaperComparator,
    PaperCardRecord,
)
from academic_tasks.drafting import AcademicDrafter, DraftResult
from academic_tasks.literature_review import LiteratureReview, LiteratureReviewService
from academic_tasks.paper_analysis import EvidencePassage, PaperCardExtractor
from academic_tasks.rewriting import AcademicRewriter, RewriteMode, RewriteResult
from academic_tasks.writing_brief import (
    EvidenceMapItem,
    SourceMaterial,
    WritingBrief,
    WritingBriefBuilder,
)
from subagents.paper_reader import PaperCard
from tool_runtime.runtime import ToolContext, ToolDefinition, ToolPolicy, ToolRegistry


class ExtractPaperCardInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    passages: list[EvidencePassage]


class ExtractPaperCardOutput(BaseModel):
    card: PaperCard


class ComparePapersInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    papers: list[PaperCardRecord]
    dimensions: list[str] = Field(min_length=1)


class BuildWritingBriefInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    section_type: str
    target_language: str
    target_length: int
    style: str
    user_points: list[str]
    materials: list[SourceMaterial]
    immutable_items: list[str]


class DraftInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    brief: WritingBrief


class RewriteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str
    mode: RewriteMode
    protected_terms: list[str] = Field(default_factory=list)


class LiteratureReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evidence_map: list[EvidenceMapItem]
    themes: dict[str, list[str]]
    inferences: list[str] = Field(default_factory=list)


class ExtractPaperCardTool(ToolDefinition[ExtractPaperCardInput, ExtractPaperCardOutput]):
    name = "extract_paper_card"
    description = "Build a Paper Card strictly from supplied evidence passages."
    input_model = ExtractPaperCardInput
    output_model = ExtractPaperCardOutput
    policy = ToolPolicy(permission="workspace:read")

    async def execute(
        self, context: ToolContext, arguments: ExtractPaperCardInput
    ) -> ExtractPaperCardOutput:
        return ExtractPaperCardOutput(card=PaperCardExtractor().extract(arguments.passages))


class BuildComparisonTableTool(ToolDefinition[ComparePapersInput, ComparisonResult]):
    name = "build_comparison_table"
    description = "Normalize Paper Cards and build an evidence-preserving matrix."
    input_model = ComparePapersInput
    output_model = ComparisonResult
    policy = ToolPolicy(permission="workspace:read")

    async def execute(
        self, context: ToolContext, arguments: ComparePapersInput
    ) -> ComparisonResult:
        return MultiPaperComparator().compare(arguments.papers, arguments.dimensions)


class BuildWritingBriefTool(ToolDefinition[BuildWritingBriefInput, WritingBrief]):
    name = "build_writing_brief"
    description = "Build a Writing Brief and Evidence Map before drafting."
    input_model = BuildWritingBriefInput
    output_model = WritingBrief
    policy = ToolPolicy(permission="workspace:read")

    async def execute(
        self, context: ToolContext, arguments: BuildWritingBriefInput
    ) -> WritingBrief:
        return WritingBriefBuilder().build(
            section_type=arguments.section_type,
            target_language=arguments.target_language,
            target_length=arguments.target_length,
            style=arguments.style,
            user_points=arguments.user_points,
            materials=arguments.materials,
            immutable_items=arguments.immutable_items,
        )


class DraftPaperSectionTool(ToolDefinition[DraftInput, DraftResult]):
    name = "draft_paper_section"
    description = "Draft a review-required section from a Writing Brief."
    input_model = DraftInput
    output_model = DraftResult
    policy = ToolPolicy(permission="workspace:write", side_effect="write")

    async def execute(self, context: ToolContext, arguments: DraftInput) -> DraftResult:
        return AcademicDrafter().draft(arguments.brief)


class RewriteAcademicTextTool(ToolDefinition[RewriteInput, RewriteResult]):
    name = "rewrite_academic_text"
    description = "Rewrite academic text with invariant regression checks."
    input_model = RewriteInput
    output_model = RewriteResult
    policy = ToolPolicy(permission="workspace:write", side_effect="write")

    async def execute(self, context: ToolContext, arguments: RewriteInput) -> RewriteResult:
        return AcademicRewriter().rewrite(
            arguments.text,
            arguments.mode,
            protected_terms=arguments.protected_terms,
        )


class LiteratureReviewTool(ToolDefinition[LiteratureReviewInput, LiteratureReview]):
    name = "build_literature_review"
    description = "Build an evidence-matrix-first literature review."
    input_model = LiteratureReviewInput
    output_model = LiteratureReview
    policy = ToolPolicy(permission="workspace:write", side_effect="write")

    async def execute(
        self, context: ToolContext, arguments: LiteratureReviewInput
    ) -> LiteratureReview:
        return LiteratureReviewService().build(
            arguments.evidence_map,
            themes=arguments.themes,
            inferences=arguments.inferences,
        )


def register_academic_tools(registry: ToolRegistry) -> None:
    for tool in (
        ExtractPaperCardTool(),
        BuildComparisonTableTool(),
        BuildWritingBriefTool(),
        DraftPaperSectionTool(),
        RewriteAcademicTextTool(),
        LiteratureReviewTool(),
    ):
        registry.register(tool)
