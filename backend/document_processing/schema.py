"""Structured document parsing schemas."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class BoundingBox(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x0: float
    y0: float
    x1: float
    y1: float


class TextBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")
    block_id: str
    page_number: int = Field(ge=1)
    text: str
    bbox: BoundingBox
    font_size: float
    font_name: str = ""
    is_bold: bool = False
    role: str = "body"
    reading_order: int = Field(ge=0)


class VisualArtifact(BaseModel):
    """A precisely cropped non-body region extracted from a PDF page."""

    model_config = ConfigDict(extra="forbid")
    artifact_id: str
    kind: Literal["figure", "table", "algorithm"]
    label: str
    caption: str = ""
    page_number: int = Field(ge=1)
    bbox: BoundingBox
    section_id: str | None = None
    section_path: list[str] = Field(default_factory=list)
    source_block_ids: list[str] = Field(default_factory=list)
    storage_path: str = ""
    image_png: bytes = Field(default=b"", exclude=True, repr=False)


class ParsedPage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page_number: int = Field(ge=1)
    width: float
    height: float
    blocks: list[TextBlock]
    text: str
    image_coverage: float = Field(ge=0, le=1)
    layout: Literal["single_column", "double_column"] = "single_column"
    column_count: int = Field(default=1, ge=1, le=2)


class DocumentSection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    section_id: str
    number: str | None = None
    title: str
    normalized_title: str = ""
    level: int = Field(ge=1)
    parent_section_id: str | None = None
    section_path: list[str] = Field(default_factory=list)
    page_start: int = Field(ge=1)
    page_end: int = Field(ge=1)
    heading_block_id: str = ""
    block_ids: list[str]
    descendant_block_ids: list[str] = Field(default_factory=list)
    ordinal: int = Field(default=0, ge=0)


class ParseQuality(BaseModel):
    model_config = ConfigDict(extra="forbid")
    score: float = Field(ge=0, le=1)
    character_count: int = Field(ge=0)
    pages_with_text: int = Field(ge=0)
    empty_page_ratio: float = Field(ge=0, le=1)
    warnings: list[str]


class ParsedDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filename: str
    page_count: int = Field(ge=0)
    pages: list[ParsedPage]
    sections: list[DocumentSection]
    headers: list[str]
    footers: list[str]
    full_text: str
    quality: ParseQuality
    parser_name: str
    parser_version: str
    visual_artifacts: list[VisualArtifact] = Field(default_factory=list)
