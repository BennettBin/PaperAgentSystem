"""Offline Docling layout candidate Adapter for selected complex PDF pages."""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import importlib.metadata
import time
from collections import defaultdict
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, Literal, Protocol

import fitz  # type: ignore[import-untyped]

from backend.core.errors import ErrorCode, ProjectError
from backend.core.ports.document_processing import DocumentLayoutAdapter
from backend.document_processing.config import DocumentProcessingConfig
from backend.document_processing.coordinates import CoordinateTransformer
from backend.document_processing.profiler import PageProfiler
from backend.document_processing.router import DeterministicParseRouter
from backend.document_processing.schema_v2 import (
    AdapterParseResult,
    CanonicalBoundingBox,
    CanonicalPage,
    CoordinateSpace,
    DocumentElement,
    DocumentRoutePlan,
    ElementType,
    PageProfile,
    PageQuality,
    PageSelection,
    ParseRoute,
    ParserProvenance,
    ParsingContext,
    QualityStatus,
    normalize_element_text,
    stable_element_id,
)

DOCLING_VERSION = "2.115.0"
DOCLING_CORE_VERSION = "2.90.0"
DOCLING_PARSE_VERSION = "7.10.0"
DOCLING_MODEL_VERSION = "3.13.0"


@dataclass(frozen=True, slots=True)
class DoclingBoundingBox:
    left: float
    top: float
    right: float
    bottom: float
    coordinate_origin: Literal["top_left", "bottom_left"] = "top_left"

    def __post_init__(self) -> None:
        if self.right < self.left:
            raise ValueError("Docling bbox right coordinate precedes left coordinate")


@dataclass(frozen=True, slots=True)
class DoclingCellCandidate:
    row_index: int
    column_index: int
    row_span: int
    column_span: int
    text: str
    bbox: DoclingBoundingBox
    confidence: float = 1.0


@dataclass(frozen=True, slots=True)
class DoclingItemCandidate:
    item_id: str
    subset_page_number: int
    label: str
    content_layer: str
    text: str
    bbox: DoclingBoundingBox
    reading_order: int
    hierarchy_level: int
    parent_item_id: str | None = None
    confidence: float = 1.0
    cells: tuple[DoclingCellCandidate, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DoclingBackendResult:
    items: tuple[DoclingItemCandidate, ...]
    failed_subset_pages: tuple[int, ...] = ()
    warnings: tuple[str, ...] = ()
    page_warnings: dict[int, tuple[str, ...]] | None = None


class DoclingBackend(Protocol):
    def convert(
        self,
        subset_pdf: bytes,
        filename: str,
        timeout_seconds: float,
    ) -> DoclingBackendResult: ...


class LocalDoclingBackend:
    """Pinned local Docling runtime with all outbound/enrichment features disabled."""

    def __init__(self, *, artifacts_path: str | None = None) -> None:
        self._artifacts_path = artifacts_path

    def convert(
        self,
        subset_pdf: bytes,
        filename: str,
        timeout_seconds: float,
    ) -> DoclingBackendResult:
        self._verify_versions_and_artifacts()
        assert self._artifacts_path is not None
        base_models = importlib.import_module("docling.datamodel.base_models")
        pipeline_module = importlib.import_module("docling.datamodel.pipeline_options")
        converter_module = importlib.import_module("docling.document_converter")

        pipeline_options = pipeline_module.PdfPipelineOptions(
            artifacts_path=Path(self._artifacts_path),
            document_timeout=timeout_seconds,
            enable_remote_services=False,
            allow_external_plugins=False,
            do_ocr=False,
            do_table_structure=True,
            do_picture_description=False,
            do_code_enrichment=False,
            do_formula_enrichment=False,
            generate_page_images=False,
            generate_picture_images=False,
            generate_table_images=False,
        )
        converter = converter_module.DocumentConverter(
            allowed_formats=[base_models.InputFormat.PDF],
            format_options={
                base_models.InputFormat.PDF: converter_module.PdfFormatOption(
                    pipeline_options=pipeline_options,
                )
            },
        )
        source = base_models.DocumentStream(
            name=filename,
            stream=BytesIO(subset_pdf),
        )
        with fitz.open(stream=subset_pdf, filetype="pdf") as subset_document:
            subset_page_count = subset_document.page_count
        conversion = converter.convert(
            source,
            raises_on_error=False,
            max_num_pages=subset_page_count,
            max_file_size=len(subset_pdf),
        )
        return _normalize_docling_conversion(conversion, subset_page_count)

    def _verify_versions_and_artifacts(self) -> None:
        try:
            runtime_version = importlib.metadata.version("docling-slim")
            core_version = importlib.metadata.version("docling-core")
            parse_version = importlib.metadata.version("docling-parse")
            model_version = importlib.metadata.version("docling-ibm-models")
        except importlib.metadata.PackageNotFoundError as exc:
            raise ModuleNotFoundError("Docling optional dependencies are not installed") from exc
        if (
            runtime_version != DOCLING_VERSION
            or core_version != DOCLING_CORE_VERSION
            or parse_version != DOCLING_PARSE_VERSION
            or model_version != DOCLING_MODEL_VERSION
        ):
            raise RuntimeError(
                "Unsupported Docling runtime/core/parser/model versions: "
                f"{runtime_version}/{core_version}/{parse_version}/{model_version}; expected "
                f"{DOCLING_VERSION}/{DOCLING_CORE_VERSION}/"
                f"{DOCLING_PARSE_VERSION}/{DOCLING_MODEL_VERSION}"
            )
        if self._artifacts_path is None or not Path(self._artifacts_path).is_dir():
            raise RuntimeError("A pre-fetched local Docling artifacts directory is required")


@dataclass(frozen=True, slots=True)
class _PageSource:
    transformer: CoordinateTransformer
    profile: PageProfile


@dataclass(frozen=True, slots=True)
class _ElementDraft:
    key: str
    parent_key: str | None
    element_type: ElementType
    text: str
    bbox: CanonicalBoundingBox
    confidence: float
    metadata: dict[str, str | int | float | bool | None]
    warnings: tuple[str, ...] = ()


class DoclingLayoutAdapter(DocumentLayoutAdapter):
    name = "docling-layout-v2"
    version = "2.0.0"
    model_name = "docling-layout-tableformer"
    model_version = DOCLING_MODEL_VERSION

    def __init__(
        self,
        config: DocumentProcessingConfig | None = None,
        *,
        backend: DoclingBackend | None = None,
        profiler: PageProfiler | None = None,
        router: DeterministicParseRouter | None = None,
    ) -> None:
        self._config = config or DocumentProcessingConfig()
        self._backend = backend or LocalDoclingBackend(
            artifacts_path=self._config.docling_artifacts_path
        )
        self._profiler = profiler or PageProfiler()
        self._router = router or DeterministicParseRouter(self._config)

    async def supports_format(self, filename: str) -> bool:
        return filename.casefold().endswith(".pdf")

    async def parse_pages(
        self,
        file_data: bytes,
        filename: str,
        selection: PageSelection,
        context: ParsingContext,
    ) -> AdapterParseResult:
        if not await self.supports_format(filename):
            raise ProjectError(ErrorCode.PARSING_FAILED, "Docling V2 Adapter requires a PDF")
        checksum = hashlib.sha256(file_data).hexdigest()
        if checksum != context.document_checksum:
            raise ProjectError(
                ErrorCode.FAILED_PRECONDITION,
                "Parser context checksum does not match PDF bytes",
                details={"reason": "document_checksum_mismatch"},
            )
        subset_pdf, subset_map, page_sources = self._prepare_subset(
            file_data,
            selection,
        )
        effective_selection = selection.model_copy(
            update={"original_page_map": subset_map}
        )
        started = time.perf_counter()
        timeout_seconds = min(
            context.timeout_seconds,
            self._config.parse_timeout_seconds,
        )
        try:
            backend_result = await asyncio.wait_for(
                asyncio.to_thread(
                    self._backend.convert,
                    subset_pdf,
                    filename,
                    timeout_seconds,
                ),
                timeout=timeout_seconds,
            )
        except TimeoutError:
            return self._failed_result(
                effective_selection,
                started,
                "docling_timeout",
            )
        except ModuleNotFoundError:
            return self._failed_result(
                effective_selection,
                started,
                "docling_dependency_unavailable",
            )
        except Exception:
            return self._failed_result(
                effective_selection,
                started,
                "docling_model_initialization_failed",
            )

        return self._map_result(
            backend_result,
            effective_selection,
            subset_map,
            page_sources,
            checksum,
            started,
        )

    def _prepare_subset(
        self,
        file_data: bytes,
        selection: PageSelection,
    ) -> tuple[bytes, dict[int, int], dict[int, _PageSource]]:
        try:
            document = fitz.open(stream=file_data, filetype="pdf")
        except Exception as exc:
            raise ProjectError(ErrorCode.PARSING_FAILED, "Invalid PDF document", cause=exc) from exc
        subset = fitz.open()
        page_sources: dict[int, _PageSource] = {}
        subset_map: dict[int, int] = {}
        try:
            if any(page > document.page_count for page in selection.page_numbers):
                raise ProjectError(
                    ErrorCode.OUT_OF_RANGE,
                    "Selected PDF page is outside the document",
                )
            for subset_page, original_page in enumerate(selection.page_numbers, start=1):
                source_page = document[original_page - 1]
                subset.insert_pdf(
                    document,
                    from_page=original_page - 1,
                    to_page=original_page - 1,
                )
                signals = self._profiler.profile_page(source_page, original_page)
                routed_profile = self._router.profile(signals)
                profile = routed_profile.model_copy(
                    update={
                        "proposed_route": ParseRoute.LAYOUT_NATIVE,
                        "route_reasons": tuple(
                            dict.fromkeys(
                                (*routed_profile.route_reasons, "docling_layout_candidate")
                            )
                        ),
                    }
                )
                page_sources[original_page] = _PageSource(
                    transformer=CoordinateTransformer.from_page(
                        source_page,
                        render_scale=self._config.render_scale,
                    ),
                    profile=profile,
                )
                subset_map[subset_page] = original_page
            output = BytesIO()
            subset.save(output, garbage=4, deflate=True, no_new_id=True)
            return output.getvalue(), subset_map, page_sources
        finally:
            subset.close()
            document.close()

    def _map_result(
        self,
        backend_result: DoclingBackendResult,
        selection: PageSelection,
        subset_map: dict[int, int],
        page_sources: dict[int, _PageSource],
        checksum: str,
        started: float,
    ) -> AdapterParseResult:
        failed_subset = set(backend_result.failed_subset_pages)
        if not failed_subset <= set(subset_map):
            return self._failed_result(
                selection,
                started,
                "docling_invalid_failed_page",
            )
        grouped: dict[int, list[DoclingItemCandidate]] = defaultdict(list)
        for item in backend_result.items:
            if item.subset_page_number not in subset_map:
                return self._failed_result(
                    selection,
                    started,
                    "docling_invalid_item_page",
                )
            if item.subset_page_number not in failed_subset:
                grouped[item.subset_page_number].append(item)
        for subset_page in subset_map:
            if subset_page not in failed_subset and not grouped[subset_page]:
                failed_subset.add(subset_page)

        page_warnings = backend_result.page_warnings or {}
        pages = tuple(
            self._map_page(
                grouped[subset_page],
                original_page=subset_map[subset_page],
                source=page_sources[subset_map[subset_page]],
                checksum=checksum,
                warnings=page_warnings.get(subset_page, ()),
            )
            for subset_page in sorted(subset_map)
            if subset_page not in failed_subset
        )
        warning_list = list(backend_result.warnings)
        for subset_page in sorted(failed_subset):
            warnings = page_warnings.get(subset_page, ()) or ("docling_page_failed",)
            warning_list.extend(
                f"page_{subset_map[subset_page]}:{warning}" for warning in warnings
            )
        return AdapterParseResult(
            parser_name=self.name,
            parser_version=self.version,
            selection=selection,
            pages=pages,
            warnings=tuple(dict.fromkeys(warning_list)),
            failed_pages=tuple(subset_map[page] for page in sorted(failed_subset)),
            model_name=self.model_name,
            model_version=self.model_version,
            duration_ms=_elapsed_ms(started),
        )

    def _map_page(
        self,
        items: list[DoclingItemCandidate],
        *,
        original_page: int,
        source: _PageSource,
        checksum: str,
        warnings: tuple[str, ...],
    ) -> CanonicalPage:
        drafts: list[_ElementDraft] = []
        item_keys = {item.item_id for item in items}
        for item in sorted(items, key=lambda value: (value.reading_order, value.item_id)):
            bbox = _canonical_docling_box(item.bbox, source.transformer)
            parent_key = item.parent_item_id if item.parent_item_id in item_keys else None
            drafts.append(
                _ElementDraft(
                    key=item.item_id,
                    parent_key=parent_key,
                    element_type=_element_type(item.label),
                    text=item.text,
                    bbox=bbox,
                    confidence=_confidence(item.confidence),
                    metadata={
                        "content_layer": item.content_layer,
                        "hierarchy_level": item.hierarchy_level,
                        "docling_item_id": item.item_id,
                        "docling_reading_order": item.reading_order,
                        "docling_parent_item_id": item.parent_item_id,
                    },
                    warnings=item.warnings,
                )
            )
            for cell_number, cell in enumerate(item.cells):
                drafts.append(
                    _ElementDraft(
                        key=f"{item.item_id}/cell/{cell_number}",
                        parent_key=item.item_id,
                        element_type=ElementType.TABLE_CELL,
                        text=cell.text,
                        bbox=_canonical_docling_box(cell.bbox, source.transformer),
                        confidence=_confidence(cell.confidence),
                        metadata={
                            "content_layer": item.content_layer,
                            "hierarchy_level": item.hierarchy_level + 1,
                            "row_index": cell.row_index,
                            "column_index": cell.column_index,
                            "row_span": cell.row_span,
                            "column_span": cell.column_span,
                        },
                    )
                )

        identifiers = {
            draft.key: stable_element_id(
                checksum,
                original_page,
                draft.element_type,
                order,
                draft.bbox,
                draft.text,
            )
            for order, draft in enumerate(drafts)
        }
        children: dict[str, list[str]] = defaultdict(list)
        for draft in drafts:
            if draft.parent_key in identifiers:
                children[draft.parent_key].append(identifiers[draft.key])
        elements = tuple(
            DocumentElement(
                element_id=identifiers[draft.key],
                page_number=original_page,
                element_type=draft.element_type,
                text=draft.text,
                normalized_text=normalize_element_text(draft.text),
                bbox=draft.bbox,
                normalized_bbox=source.transformer.normalize(draft.bbox),
                reading_order=order,
                provenance=ParserProvenance(
                    parser_name=self.name,
                    parser_version=self.version,
                    model_name=self.model_name,
                    model_version=self.model_version,
                    confidence=draft.confidence,
                    source_coordinate_space=CoordinateSpace.PDF_POINT,
                    is_inferred=True,
                    warnings=draft.warnings,
                ),
                parent_id=(
                    identifiers.get(draft.parent_key)
                    if draft.parent_key is not None
                    else None
                ),
                children_ids=tuple(children[draft.key]),
                is_inferred=True,
                metadata=draft.metadata,
            )
            for order, draft in enumerate(drafts)
        )
        average_confidence = (
            sum(element.provenance.confidence for element in elements) / len(elements)
            if elements
            else 0.0
        )
        table_items = [item for item in elements if item.element_type is ElementType.TABLE]
        table_cells = [item for item in elements if item.element_type is ElementType.TABLE_CELL]
        table_score = 1.0 if not table_items or table_cells else 0.5
        return CanonicalPage(
            page_number=original_page,
            width=source.transformer.page_width,
            height=source.transformer.page_height,
            rotation=source.transformer.rotation,
            cropbox=CanonicalBoundingBox(
                x0=0,
                y0=0,
                x1=source.transformer.page_width,
                y1=source.transformer.page_height,
            ),
            selected_route=ParseRoute.LAYOUT_NATIVE,
            route_reasons=source.profile.route_reasons,
            profile=source.profile,
            elements=elements,
            quality=PageQuality(
                status=(
                    QualityStatus.PASS
                    if not warnings
                    else QualityStatus.PASS_WITH_WARNINGS
                ),
                overall=average_confidence,
                text=average_confidence,
                coordinates=1.0,
                reading_order=average_confidence,
                structure=average_confidence,
                ocr=1.0,
                tables=table_score,
                completeness=average_confidence,
                warnings=warnings,
            ),
        )

    def _failed_result(
        self,
        selection: PageSelection,
        started: float,
        warning: str,
    ) -> AdapterParseResult:
        return AdapterParseResult(
            parser_name=self.name,
            parser_version=self.version,
            selection=selection,
            pages=(),
            warnings=(warning,),
            failed_pages=selection.page_numbers,
            model_name=self.model_name,
            model_version=self.model_version,
            duration_ms=_elapsed_ms(started),
        )


async def parse_docling_candidates(
    adapter: DoclingLayoutAdapter,
    file_data: bytes,
    filename: str,
    route_plan: DocumentRoutePlan,
    context: ParsingContext,
) -> AdapterParseResult | None:
    """Invoke Docling only for pages selected by the deterministic layout route."""

    pages = tuple(
        decision.page_number
        for decision in route_plan.decisions
        if decision.route is ParseRoute.LAYOUT_NATIVE
    )
    if not pages:
        return None
    return await adapter.parse_pages(
        file_data,
        filename,
        PageSelection(page_numbers=pages),
        context,
    )


def _canonical_docling_box(
    bbox: DoclingBoundingBox,
    transformer: CoordinateTransformer,
) -> CanonicalBoundingBox:
    x0 = min(max(0.0, bbox.left), transformer.page_width)
    x1 = min(max(0.0, bbox.right), transformer.page_width)
    vertical_min = min(bbox.top, bbox.bottom)
    vertical_max = max(bbox.top, bbox.bottom)
    if bbox.coordinate_origin == "bottom_left":
        y0 = transformer.page_height - vertical_max
        y1 = transformer.page_height - vertical_min
    else:
        y0 = vertical_min
        y1 = vertical_max
    return CanonicalBoundingBox(
        x0=min(x0, x1),
        y0=min(max(0.0, y0), transformer.page_height),
        x1=max(x0, x1),
        y1=min(max(0.0, y1), transformer.page_height),
    )


def _element_type(label: str) -> ElementType:
    normalized = label.casefold()
    mapping = {
        "title": ElementType.TITLE,
        "section_header": ElementType.SECTION_HEADING,
        "paragraph": ElementType.PARAGRAPH,
        "text": ElementType.PARAGRAPH,
        "list_item": ElementType.LIST_ITEM,
        "caption": ElementType.CAPTION,
        "page_header": ElementType.PAGE_HEADER,
        "page_footer": ElementType.PAGE_FOOTER,
        "footnote": ElementType.FOOTNOTE,
        "table": ElementType.TABLE,
        "picture": ElementType.FIGURE,
        "chart": ElementType.FIGURE,
        "formula": ElementType.EQUATION,
        "code": ElementType.CODE,
        "reference": ElementType.REFERENCE,
    }
    return mapping.get(normalized, ElementType.UNKNOWN)


def _normalize_docling_conversion(
    conversion: Any,
    subset_page_count: int,
) -> DoclingBackendResult:
    document = conversion.document
    items: list[DoclingItemCandidate] = []
    for reading_order, (item, level) in enumerate(document.iterate_items()):
        provenance = getattr(item, "prov", ())
        if not provenance:
            continue
        prov = provenance[0]
        bbox = _docling_bbox(prov.bbox)
        cells = _docling_cells(item)
        items.append(
            DoclingItemCandidate(
                item_id=str(item.self_ref),
                parent_item_id=_reference_value(getattr(item, "parent", None)),
                subset_page_number=int(prov.page_no),
                label=_enum_value(item.label),
                content_layer=_enum_value(item.content_layer),
                text=_docling_item_text(item, document),
                bbox=bbox,
                reading_order=reading_order,
                hierarchy_level=int(level),
                confidence=_item_confidence(item),
                cells=cells,
            )
        )
    failed, page_warnings = _docling_errors(conversion, subset_page_count)
    present_pages = {item.subset_page_number for item in items}
    status = _enum_value(getattr(conversion, "status", "success"))
    if status == "failure":
        failed.update(range(1, subset_page_count + 1))
    elif status == "partial_success":
        failed.update(set(range(1, subset_page_count + 1)) - present_pages)
    return DoclingBackendResult(
        items=tuple(items),
        failed_subset_pages=tuple(sorted(failed)),
        page_warnings={page: tuple(values) for page, values in page_warnings.items()},
    )


def _docling_bbox(value: Any) -> DoclingBoundingBox:
    return DoclingBoundingBox(
        left=float(value.l),
        top=float(value.t),
        right=float(value.r),
        bottom=float(value.b),
        coordinate_origin=(
            "bottom_left"
            if _enum_value(getattr(value, "coord_origin", "top_left")).casefold()
            == "bottomleft"
            else "top_left"
        ),
    )


def _docling_cells(item: Any) -> tuple[DoclingCellCandidate, ...]:
    data = getattr(item, "data", None)
    table_cells = getattr(data, "table_cells", ())
    result: list[DoclingCellCandidate] = []
    for cell in table_cells:
        bbox = getattr(cell, "bbox", None)
        if bbox is None:
            continue
        result.append(
            DoclingCellCandidate(
                row_index=int(cell.start_row_offset_idx),
                column_index=int(cell.start_col_offset_idx),
                row_span=max(1, int(cell.row_span)),
                column_span=max(1, int(cell.col_span)),
                text=str(cell.text),
                bbox=_docling_bbox(bbox),
                confidence=_item_confidence(cell),
            )
        )
    return tuple(result)


def _docling_item_text(item: Any, document: Any) -> str:
    text = getattr(item, "text", None)
    if text is not None:
        return str(text)
    exporter = getattr(item, "export_to_markdown", None)
    if exporter is not None:
        try:
            return str(exporter(doc=document))
        except Exception:
            return ""
    return ""


def _docling_errors(
    conversion: Any,
    subset_page_count: int,
) -> tuple[set[int], dict[int, list[str]]]:
    failed: set[int] = set()
    warnings: dict[int, list[str]] = defaultdict(list)
    for error in getattr(conversion, "errors", ()):
        page = getattr(error, "page_no", None)
        if page is None:
            page = getattr(getattr(error, "error", None), "page_no", None)
        message = normalize_element_text(str(getattr(error, "error_message", error)))
        if isinstance(page, int) and 1 <= page <= subset_page_count:
            failed.add(page)
            warnings[page].append(message or "docling_page_failed")
    return failed, warnings


def _reference_value(reference: Any) -> str | None:
    if reference is None:
        return None
    return str(getattr(reference, "cref", getattr(reference, "$ref", reference)))


def _enum_value(value: Any) -> str:
    return str(getattr(value, "value", value)).casefold()


def _item_confidence(item: Any) -> float:
    confidence = getattr(item, "confidence", None)
    if confidence is None:
        confidence = getattr(getattr(item, "meta", None), "confidence", 0.9)
    if confidence is None:
        return 0.9
    try:
        return _confidence(float(confidence))
    except (TypeError, ValueError):
        return 0.9


def _confidence(value: float) -> float:
    return min(1.0, max(0.0, value))


def _elapsed_ms(started: float) -> float:
    return max(0.0, (time.perf_counter() - started) * 1000)
