"""RAG document and chunk schemas."""

from pydantic import BaseModel, ConfigDict, Field

from document_processing.schema import BoundingBox


class DocumentChunk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_id: str
    document_id: str
    workspace_id: str
    file_id: str
    parent_chunk_id: str | None
    level: str
    section_path: list[str]
    text: str
    page_start: int = Field(ge=1)
    page_end: int = Field(ge=1)
    bbox: BoundingBox
    source_block_ids: list[str] = Field(min_length=1)
    previous_chunk_id: str | None = None
    next_chunk_id: str | None = None
    embedding: list[float] = Field(default_factory=list)
    embedding_model: str = ""
