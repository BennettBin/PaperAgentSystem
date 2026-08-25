"""Provider-neutral request and response contract for document VLM services."""

from __future__ import annotations

from enum import Enum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.document_processing.schema_v2 import ElementType


class FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class VLMContentKind(str, Enum):
    OCR_TEXT = "ocr_text"
    GENERATED_DESCRIPTION = "generated_description"


class VLMResponseStatus(str, Enum):
    SUCCESS = "success"
    SERVICE_UNAVAILABLE = "service_unavailable"
    TIMEOUT = "timeout"
    OOM = "oom"
    INVALID_RESPONSE = "invalid_response"
    FATAL_ERROR = "fatal_error"


class PixelBoundingBox(FrozenContract):
    x0: float = Field(ge=0)
    y0: float = Field(ge=0)
    x1: float = Field(ge=0)
    y1: float = Field(ge=0)

    @model_validator(mode="after")
    def validate_order(self) -> "PixelBoundingBox":
        if self.x1 < self.x0 or self.y1 < self.y0:
            raise ValueError("pixel bbox maximum coordinates must not precede minimum coordinates")
        return self


class VLMTableCellCandidate(FrozenContract):
    row_index: int = Field(ge=0)
    column_index: int = Field(ge=0)
    row_span: int = Field(default=1, ge=1)
    column_span: int = Field(default=1, ge=1)
    text: str = ""
    bbox: PixelBoundingBox
    confidence: float = Field(ge=0, le=1)


class VLMElementCandidate(FrozenContract):
    element_type: ElementType
    text: str = ""
    original_text: str | None = None
    bbox: PixelBoundingBox
    reading_order: int = Field(ge=0)
    confidence: float = Field(ge=0, le=1)
    content_kind: VLMContentKind = VLMContentKind.OCR_TEXT
    language: str = "und"
    latex: str | None = None
    cells: tuple[VLMTableCellCandidate, ...] = ()
    warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_content_separation(self) -> "VLMElementCandidate":
        if (
            self.content_kind is VLMContentKind.GENERATED_DESCRIPTION
            and self.original_text is not None
        ):
            raise ValueError("generated descriptions cannot carry OCR original_text")
        if self.cells and self.element_type is not ElementType.TABLE:
            raise ValueError("only table elements may contain table cells")
        if self.latex is not None and self.element_type is not ElementType.EQUATION:
            raise ValueError("only equation elements may contain LaTeX")
        return self


class VLMPageRequest(FrozenContract):
    request_id: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    page_number: int = Field(ge=1)
    image_bytes: bytes = Field(min_length=1)
    image_width: int = Field(gt=0)
    image_height: int = Field(gt=0)
    expected_languages: tuple[str, ...] = ("und",)
    allowed_element_types: tuple[ElementType, ...]
    document_content_is_untrusted: bool = True

    @model_validator(mode="after")
    def validate_security_contract(self) -> "VLMPageRequest":
        if not self.document_content_is_untrusted:
            raise ValueError("document content must always be treated as untrusted data")
        if not self.allowed_element_types:
            raise ValueError("at least one output element type must be allowed")
        return self


class VLMPageResponse(FrozenContract):
    request_id: str = Field(min_length=1)
    page_number: int = Field(ge=1)
    status: VLMResponseStatus
    model_name: str = Field(min_length=1)
    model_version: str = Field(min_length=1)
    elements: tuple[VLMElementCandidate, ...] = ()
    warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_status_payload(self) -> "VLMPageResponse":
        if self.status is not VLMResponseStatus.SUCCESS and self.elements:
            raise ValueError("failed VLM responses cannot contain candidate elements")
        return self


class DocumentVLMProvider(Protocol):
    async def infer(
        self,
        request: VLMPageRequest,
        *,
        timeout_seconds: float,
    ) -> VLMPageResponse: ...
