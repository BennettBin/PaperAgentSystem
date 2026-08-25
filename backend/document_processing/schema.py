"""Shared geometry and rendered-artifact value objects.

The retired ParsedDocument V1 graph intentionally does not live here. All parsed
document writes use :mod:`backend.document_processing.schema_v2`.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class BoundingBox(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x0: float
    y0: float
    x1: float
    y1: float


class VisualArtifact(BaseModel):
    """A precisely cropped non-body region extracted from a document page."""

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
