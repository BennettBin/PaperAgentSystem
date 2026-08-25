"""Canonical, parser-neutral document representation for hybrid parsing V2."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from enum import Enum
from typing import Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

JSONScalar: TypeAlias = str | int | float | bool | None
Rotation: TypeAlias = Literal[0, 90, 180, 270]
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ParseRoute(str, Enum):
    FAST_NATIVE = "fast_native"
    LAYOUT_NATIVE = "layout_native"
    DOCUMENT_VLM = "document_vlm"
    FAILED = "failed"


class ElementType(str, Enum):
    TITLE = "title"
    SECTION_HEADING = "section_heading"
    PARAGRAPH = "paragraph"
    LIST_ITEM = "list_item"
    CAPTION = "caption"
    PAGE_HEADER = "page_header"
    PAGE_FOOTER = "page_footer"
    FOOTNOTE = "footnote"
    TABLE = "table"
    TABLE_CELL = "table_cell"
    FIGURE = "figure"
    EQUATION = "equation"
    CODE = "code"
    ALGORITHM = "algorithm"
    REFERENCE = "reference"
    TEXT_LINE = "text_line"
    TEXT_SPAN = "text_span"
    UNKNOWN = "unknown"


class CoordinateSpace(str, Enum):
    PDF_POINT = "pdf_point"
    NORMALIZED = "normalized"
    RENDER_PIXEL = "render_pixel"
    OFFICE_LAYOUT = "office_layout"


class QualityStatus(str, Enum):
    PASS = "pass"
    PASS_WITH_WARNINGS = "pass_with_warnings"
    RETRY_WITH_VLM = "retry_with_vlm"
    FAILED = "failed"


class LocatorType(str, Enum):
    PDF_PAGE = "pdf_page"
    DOCX_POSITION = "docx_position"
    RENDERED_PAGE = "rendered_page"
    PPTX_SLIDE = "pptx_slide"


class CanonicalBoundingBox(FrozenModel):
    x0: float = Field(ge=0)
    y0: float = Field(ge=0)
    x1: float = Field(ge=0)
    y1: float = Field(ge=0)

    @model_validator(mode="after")
    def validate_order(self) -> "CanonicalBoundingBox":
        if self.x1 < self.x0 or self.y1 < self.y0:
            raise ValueError("bbox maximum coordinates must not precede minimum coordinates")
        return self


class NormalizedBoundingBox(FrozenModel):
    x0: float = Field(ge=0, le=1)
    y0: float = Field(ge=0, le=1)
    x1: float = Field(ge=0, le=1)
    y1: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_order(self) -> "NormalizedBoundingBox":
        if self.x1 < self.x0 or self.y1 < self.y0:
            raise ValueError("normalized bbox maximum coordinates must not precede minimum coordinates")
        return self


class ParserProvenance(FrozenModel):
    parser_name: str = Field(min_length=1)
    parser_version: str = Field(min_length=1)
    model_name: str | None = None
    model_version: str | None = None
    confidence: float = Field(ge=0, le=1)
    source_coordinate_space: CoordinateSpace
    is_inferred: bool = False
    warnings: tuple[str, ...] = ()


class SourceCandidate(FrozenModel):
    candidate_id: str = Field(min_length=1)
    element_type: ElementType
    text: str = ""
    bbox: CanonicalBoundingBox
    normalized_bbox: NormalizedBoundingBox
    reading_order: int = Field(ge=0)
    provenance: ParserProvenance
    accepted: bool = False
    decision_reason: str = ""


class DocumentElement(FrozenModel):
    element_id: str = Field(pattern=r"^el_[0-9a-f]{24}$")
    page_number: int = Field(ge=1)
    element_type: ElementType
    text: str = ""
    normalized_text: str = ""
    bbox: CanonicalBoundingBox
    normalized_bbox: NormalizedBoundingBox
    reading_order: int = Field(ge=0)
    provenance: ParserProvenance
    parent_id: str | None = None
    children_ids: tuple[str, ...] = ()
    source_candidates: tuple[SourceCandidate, ...] = ()
    is_inferred: bool = False
    metadata: dict[str, JSONScalar] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_provenance(self) -> "DocumentElement":
        if self.is_inferred != self.provenance.is_inferred:
            raise ValueError("element and provenance inferred flags must agree")
        if self.parent_id == self.element_id or self.element_id in self.children_ids:
            raise ValueError("element cannot be its own parent or child")
        return self


class PageProfile(FrozenModel):
    page_number: int = Field(ge=1)
    native_character_count: int = Field(ge=0)
    garble_ratio: float = Field(ge=0, le=1)
    image_coverage: float = Field(ge=0, le=1)
    text_overlap_ratio: float = Field(ge=0, le=1)
    bbox_out_of_bounds_ratio: float = Field(ge=0, le=1)
    detected_column_count: int = Field(default=1, ge=0)
    has_tables: bool = False
    has_formulas: bool = False
    has_drawings: bool = False
    rotation: Rotation = 0
    proposed_route: ParseRoute
    route_reasons: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_route_reason(self) -> "PageProfile":
        if self.proposed_route is not ParseRoute.FAST_NATIVE and not self.route_reasons:
            raise ValueError("non-fast route requires at least one route reason")
        return self


class PageSignals(FrozenModel):
    page_number: int = Field(ge=1)
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    rotation: Rotation = 0
    cropbox: CanonicalBoundingBox
    mediabox: CanonicalBoundingBox
    native_character_count: int = Field(ge=0)
    character_density: float = Field(ge=0)
    garble_ratio: float = Field(ge=0, le=1)
    image_coverage: float = Field(ge=0, le=1)
    text_overlap_ratio: float = Field(ge=0, le=1)
    bbox_out_of_bounds_ratio: float = Field(ge=0, le=1)
    detected_column_count: int = Field(default=1, ge=0)
    has_tables: bool = False
    has_formulas: bool = False
    has_drawings: bool = False
    drawing_count: int = Field(default=0, ge=0)
    suspected_duplicate_ocr: bool = False
    text_block_count: int = Field(ge=0)
    image_block_count: int = Field(ge=0)

    @property
    def cropbox_differs_from_mediabox(self) -> bool:
        return self.cropbox != self.mediabox


class RouteDecision(FrozenModel):
    page_number: int = Field(ge=1)
    route: ParseRoute
    reasons: tuple[str, ...]
    fallback_routes: tuple[ParseRoute, ...] = ()

    @model_validator(mode="after")
    def validate_reasons(self) -> "RouteDecision":
        if self.route is not ParseRoute.FAST_NATIVE and not self.reasons:
            raise ValueError("non-fast route decision requires a reason")
        if self.route in self.fallback_routes:
            raise ValueError("selected route cannot also be a fallback route")
        return self


class DocumentRoutePlan(FrozenModel):
    document_route: ParseRoute
    decisions: tuple[RouteDecision, ...]
    vlm_page_count: int = Field(ge=0)
    vlm_page_limit: int = Field(ge=0)
    budget_exceeded: bool = False
    blocked_page_numbers: tuple[int, ...] = ()

    @model_validator(mode="after")
    def validate_plan(self) -> "DocumentRoutePlan":
        pages = [decision.page_number for decision in self.decisions]
        if pages != list(range(1, len(pages) + 1)):
            raise ValueError("route decisions must be contiguous and one-based")
        actual_vlm = sum(
            decision.route is ParseRoute.DOCUMENT_VLM for decision in self.decisions
        )
        if self.vlm_page_count != actual_vlm:
            raise ValueError("VLM page count does not match route decisions")
        expected_exceeded = actual_vlm > self.vlm_page_limit
        if self.budget_exceeded != expected_exceeded:
            raise ValueError("budget flag does not match VLM page limit")
        expected_blocked = tuple(
            decision.page_number
            for decision in self.decisions
            if decision.route is ParseRoute.DOCUMENT_VLM
        )[self.vlm_page_limit :]
        if self.blocked_page_numbers != expected_blocked:
            raise ValueError("blocked pages do not match pages beyond VLM budget")
        return self


class PreflightPage(FrozenModel):
    page_number: int = Field(ge=1)
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    rotation: Rotation
    cropbox: CanonicalBoundingBox
    mediabox: CanonicalBoundingBox
    estimated_render_pixels: int = Field(ge=1)


class DocumentPreflight(FrozenModel):
    filename: str = Field(min_length=1)
    checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    detected_format: Literal["pdf"]
    file_size_bytes: int = Field(gt=0)
    page_count: int = Field(gt=0)
    encrypted: bool = False
    pages: tuple[PreflightPage, ...]
    total_estimated_render_pixels: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_preflight_pages(self) -> "DocumentPreflight":
        if self.page_count != len(self.pages):
            raise ValueError("preflight page count does not match pages")
        if [page.page_number for page in self.pages] != list(
            range(1, self.page_count + 1)
        ):
            raise ValueError("preflight pages must be contiguous and one-based")
        if self.total_estimated_render_pixels != sum(
            page.estimated_render_pixels for page in self.pages
        ):
            raise ValueError("preflight total pixel estimate does not match pages")
        return self


class PageQuality(FrozenModel):
    status: QualityStatus
    overall: float = Field(ge=0, le=1)
    text: float = Field(ge=0, le=1)
    coordinates: float = Field(ge=0, le=1)
    reading_order: float = Field(ge=0, le=1)
    structure: float = Field(ge=0, le=1)
    ocr: float = Field(ge=0, le=1)
    tables: float = Field(ge=0, le=1)
    completeness: float = Field(ge=0, le=1)
    warnings: tuple[str, ...] = ()


class CanonicalPage(FrozenModel):
    page_number: int = Field(ge=1)
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    rotation: Rotation = 0
    cropbox: CanonicalBoundingBox
    selected_route: ParseRoute
    route_reasons: tuple[str, ...] = ()
    profile: PageProfile
    elements: tuple[DocumentElement, ...]
    quality: PageQuality

    @model_validator(mode="after")
    def validate_page_elements(self) -> "CanonicalPage":
        if self.profile.page_number != self.page_number:
            raise ValueError("profile page number must match canonical page")
        if self.profile.proposed_route != self.selected_route:
            raise ValueError("selected route must match the frozen page profile route")
        ids = [element.element_id for element in self.elements]
        orders = [element.reading_order for element in self.elements]
        if len(ids) != len(set(ids)):
            raise ValueError("page element IDs must be unique")
        if len(orders) != len(set(orders)):
            raise ValueError("page reading orders must be unique")
        if any(element.page_number != self.page_number for element in self.elements):
            raise ValueError("element page number must match canonical page")
        if any(
            element.bbox.x1 > self.width or element.bbox.y1 > self.height
            for element in self.elements
        ):
            raise ValueError("canonical element bbox must remain inside page bounds")
        by_id = {element.element_id: element for element in self.elements}
        for element in self.elements:
            if element.parent_id is not None:
                parent = by_id.get(element.parent_id)
                if parent is None or element.element_id not in parent.children_ids:
                    raise ValueError("element parent reference must be reciprocal and page-local")
            for child_id in element.children_ids:
                child = by_id.get(child_id)
                if child is None or child.parent_id != element.element_id:
                    raise ValueError("element child reference must be reciprocal and page-local")
        return self


class CanonicalSection(FrozenModel):
    section_id: str = Field(pattern=r"^sec_[0-9a-f]{24}$")
    title: str = Field(min_length=1)
    number: str | None = None
    level: int = Field(ge=1)
    parent_section_id: str | None = None
    section_path: tuple[str, ...]
    page_start: int = Field(ge=1)
    page_end: int = Field(ge=1)
    heading_element_id: str
    element_ids: tuple[str, ...]
    ordinal: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_page_range(self) -> "CanonicalSection":
        if self.page_end < self.page_start:
            raise ValueError("section page range is reversed")
        return self


class TableCell(FrozenModel):
    cell_id: str = Field(pattern=r"^cell_[0-9a-f]{24}$")
    page_number: int = Field(ge=1)
    row_index: int = Field(ge=0)
    column_index: int = Field(ge=0)
    row_span: int = Field(default=1, ge=1)
    column_span: int = Field(default=1, ge=1)
    text: str = ""
    bbox: CanonicalBoundingBox
    normalized_bbox: NormalizedBoundingBox
    confidence: float = Field(ge=0, le=1)


class StructuredTable(FrozenModel):
    table_id: str = Field(pattern=r"^table_[0-9a-f]{24}$")
    page_number: int = Field(ge=1)
    caption: str = ""
    bbox: CanonicalBoundingBox
    normalized_bbox: NormalizedBoundingBox
    cells: tuple[TableCell, ...]
    source_element_ids: tuple[str, ...]
    markdown: str = ""


class Equation(FrozenModel):
    equation_id: str = Field(pattern=r"^eq_[0-9a-f]{24}$")
    page_number: int = Field(ge=1)
    latex: str
    number: str | None = None
    inline: bool = False
    bbox: CanonicalBoundingBox
    normalized_bbox: NormalizedBoundingBox
    confidence: float = Field(ge=0, le=1)
    source_element_ids: tuple[str, ...]


class Figure(FrozenModel):
    figure_id: str = Field(pattern=r"^fig_[0-9a-f]{24}$")
    page_number: int = Field(ge=1)
    caption: str = ""
    description: str = ""
    description_is_inferred: bool = False
    bbox: CanonicalBoundingBox
    normalized_bbox: NormalizedBoundingBox
    source_element_ids: tuple[str, ...]


class DocumentQuality(FrozenModel):
    status: QualityStatus
    overall: float = Field(ge=0, le=1)
    warnings: tuple[str, ...] = ()
    failed_pages: tuple[int, ...] = ()

    @property
    def ready_for_index(self) -> bool:
        return self.status in {QualityStatus.PASS, QualityStatus.PASS_WITH_WARNINGS}

    @field_validator("failed_pages")
    @classmethod
    def validate_failed_pages(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        if any(page < 1 for page in value) or len(value) != len(set(value)):
            raise ValueError("failed page numbers must be unique positive integers")
        return value


class PipelineComponent(FrozenModel):
    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    model_name: str | None = None
    model_version: str | None = None
    config: dict[str, JSONScalar] = Field(default_factory=dict)


class PipelineDescriptor(FrozenModel):
    schema_version: Literal["2.0"] = "2.0"
    router_version: str = Field(min_length=1)
    render_scale: float = Field(gt=0)
    components: tuple[PipelineComponent, ...]
    config: dict[str, JSONScalar] = Field(default_factory=dict)

    @property
    def fingerprint(self) -> str:
        payload = canonical_json(self)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class EvidenceSpan(FrozenModel):
    element_id: str
    page_number: int = Field(ge=1)
    locator_type: LocatorType = LocatorType.PDF_PAGE
    bbox: CanonicalBoundingBox
    normalized_bbox: NormalizedBoundingBox
    source_parser: str = Field(min_length=1)


class ReconciliationDecision(FrozenModel):
    decision_id: str = Field(pattern=r"^decision_[0-9a-f]{24}$")
    page_number: int = Field(ge=1)
    output_element_id: str = Field(pattern=r"^el_[0-9a-f]{24}$")
    accepted_candidate_id: str = Field(min_length=1)
    rejected_candidate_ids: tuple[str, ...] = ()
    reason: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)


class CanonicalDocumentV2(FrozenModel):
    schema_version: Literal["2.0"] = "2.0"
    document_id: str = Field(pattern=r"^doc_[0-9a-f]{24}$")
    filename: str = Field(min_length=1)
    checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    document_locator_type: LocatorType = LocatorType.PDF_PAGE
    page_count: int = Field(ge=0)
    pipeline: PipelineDescriptor
    pipeline_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    pages: tuple[CanonicalPage, ...]
    sections: tuple[CanonicalSection, ...] = ()
    tables: tuple[StructuredTable, ...] = ()
    equations: tuple[Equation, ...] = ()
    figures: tuple[Figure, ...] = ()
    reconciliation_decisions: tuple[ReconciliationDecision, ...] = ()
    quality: DocumentQuality

    @model_validator(mode="after")
    def validate_document_graph(self) -> "CanonicalDocumentV2":
        if self.pipeline_fingerprint != self.pipeline.fingerprint:
            raise ValueError("pipeline fingerprint does not match descriptor")
        if self.page_count != len(self.pages):
            raise ValueError("page count must equal number of canonical pages")
        expected_pages = list(range(1, self.page_count + 1))
        if [page.page_number for page in self.pages] != expected_pages:
            raise ValueError("canonical pages must be contiguous and one-based")
        elements = {
            element.element_id
            for page in self.pages
            for element in page.elements
        }
        element_values = {
            element.element_id: element
            for page in self.pages
            for element in page.elements
        }
        for element in element_values.values():
            accepted = [candidate for candidate in element.source_candidates if candidate.accepted]
            if len(accepted) != 1:
                raise ValueError("final element must have exactly one accepted source candidate")
        decision_outputs = [decision.output_element_id for decision in self.reconciliation_decisions]
        if len(decision_outputs) != len(set(decision_outputs)):
            raise ValueError("reconciliation decisions must have unique output elements")
        if set(decision_outputs) != elements:
            raise ValueError("every final element must have one reconciliation decision")
        for decision in self.reconciliation_decisions:
            element = element_values[decision.output_element_id]
            accepted_ids = {
                candidate.candidate_id
                for candidate in element.source_candidates
                if candidate.accepted
            }
            if decision.accepted_candidate_id not in accepted_ids:
                raise ValueError("decision must reference the accepted source candidate")
        referenced = {
            reference
            for section in self.sections
            for reference in (section.heading_element_id, *section.element_ids)
        }
        for table in self.tables:
            referenced.update(table.source_element_ids)
        for equation in self.equations:
            referenced.update(equation.source_element_ids)
        for figure in self.figures:
            referenced.update(figure.source_element_ids)
        if not referenced <= elements:
            raise ValueError("sections and artifacts must reference existing elements")
        if any(page not in expected_pages for page in self.quality.failed_pages):
            raise ValueError("failed pages must belong to this document")
        return self


class PageSelection(FrozenModel):
    page_numbers: tuple[int, ...]
    original_page_map: dict[int, int] = Field(default_factory=dict)

    @field_validator("page_numbers")
    @classmethod
    def validate_page_numbers(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        if not value or any(page < 1 for page in value):
            raise ValueError("page selection requires positive one-based page numbers")
        if tuple(sorted(set(value))) != value:
            raise ValueError("page selection must be unique and sorted")
        return value


class ParsingContext(FrozenModel):
    trace_id: str = Field(min_length=1)
    document_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    pipeline: PipelineDescriptor
    timeout_seconds: float = Field(gt=0)
    metadata: dict[str, JSONScalar] = Field(default_factory=dict)


class AdapterParseResult(FrozenModel):
    parser_name: str = Field(min_length=1)
    parser_version: str = Field(min_length=1)
    selection: PageSelection
    pages: tuple[CanonicalPage, ...]
    warnings: tuple[str, ...] = ()
    failed_pages: tuple[int, ...] = ()
    model_name: str | None = None
    model_version: str | None = None
    duration_ms: float = Field(default=0, ge=0)
    metrics: dict[str, JSONScalar] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_selected_pages(self) -> "AdapterParseResult":
        returned = tuple(page.page_number for page in self.pages)
        failed = tuple(sorted(self.failed_pages))
        if len(failed) != len(set(failed)):
            raise ValueError("failed adapter pages must be unique")
        selected = self.selection.page_numbers
        if set(returned) & set(failed):
            raise ValueError("adapter page cannot be both returned and failed")
        if tuple(sorted((*returned, *failed))) != selected:
            raise ValueError("adapter must return or fail every selected page")
        return self


def canonical_json(model: BaseModel | dict[str, Any]) -> str:
    payload = model.model_dump(mode="json") if isinstance(model, BaseModel) else model
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def normalize_element_text(value: str) -> str:
    compatibility = unicodedata.normalize("NFKC", value)
    dehyphenated = re.sub(r"(?<=\w)-\s*\n\s*(?=\w)", "", compatibility)
    return " ".join(dehyphenated.split())


def stable_identifier(prefix: str, *parts: object) -> str:
    payload = "\x1f".join(str(part) for part in parts)
    return f"{prefix}_{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:24]}"


def stable_document_id(checksum: str) -> str:
    if not SHA256_PATTERN.fullmatch(checksum):
        raise ValueError("document checksum must be a lowercase SHA-256 value")
    return stable_identifier("doc", checksum)


def stable_element_id(
    checksum: str,
    page_number: int,
    element_type: ElementType,
    reading_order: int,
    bbox: CanonicalBoundingBox,
    text: str,
) -> str:
    if not SHA256_PATTERN.fullmatch(checksum):
        raise ValueError("document checksum must be a lowercase SHA-256 value")
    return stable_identifier(
        "el",
        checksum,
        page_number,
        element_type.value,
        reading_order,
        f"{bbox.x0:.4f},{bbox.y0:.4f},{bbox.x1:.4f},{bbox.y1:.4f}",
        normalize_element_text(text),
    )
