"""RAG document and chunk schemas."""

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.document_processing.schema import BoundingBox
from backend.document_processing.schema_v2 import ElementType, EvidenceSpan


class DocumentChunk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_id: str
    document_id: str
    workspace_id: str
    file_id: str
    parent_chunk_id: str | None
    level: str
    section_id: str
    section_number: str | None = None
    section_title: str
    section_path: list[str]
    chunk_index_in_section: int = Field(default=0, ge=0)
    text: str
    page_start: int = Field(ge=1)
    page_end: int = Field(ge=1)
    bbox: BoundingBox
    source_block_ids: list[str] = Field(min_length=1)
    evidence_spans: list[EvidenceSpan] = Field(default_factory=list)
    element_types: list[ElementType] = Field(default_factory=list)
    content_kind: str = "body"
    contains_inferred_content: bool = False
    previous_chunk_id: str | None = None
    next_chunk_id: str | None = None
    embedding: list[float] = Field(default_factory=list)
    embedding_model: str = ""
    embedding_provider: str = "legacy"
    embedding_version: str = "unknown"
    embedding_dimension: int = 1024
    embedding_max_length: int = 0
    embedding_normalized: bool = True
    embedding_fingerprint: str = ""
    embedding_status: str = "ready"

    @model_validator(mode="after")
    def validate_evidence_spans(self) -> "DocumentChunk":
        if not self.evidence_spans:
            return self
        pages = [span.page_number for span in self.evidence_spans]
        if self.page_start != min(pages) or self.page_end != max(pages):
            raise ValueError("chunk page range must match its evidence spans")
        source_ids = set(self.source_block_ids)
        if any(span.element_id not in source_ids for span in self.evidence_spans):
            raise ValueError("evidence span element IDs must belong to chunk sources")
        return self
