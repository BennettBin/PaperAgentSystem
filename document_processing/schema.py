"""Structured document parsing schemas."""

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
    role: str = "body"
    reading_order: int = Field(ge=0)


class ParsedPage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page_number: int = Field(ge=1)
    width: float
    height: float
    blocks: list[TextBlock]
    text: str
    image_coverage: float = Field(ge=0, le=1)


class DocumentSection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    section_id: str
    title: str
    level: int = Field(ge=1)
    page_start: int = Field(ge=1)
    page_end: int = Field(ge=1)
    block_ids: list[str]


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
