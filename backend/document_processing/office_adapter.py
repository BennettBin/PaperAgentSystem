"""Docling-backed DOCX/PPTX Adapter producing CanonicalDocument V2."""

from __future__ import annotations

import asyncio
import importlib
import importlib.metadata
import io
import posixpath
import zipfile
from collections import defaultdict
from dataclasses import dataclass, replace
from io import BytesIO
from typing import Any, Protocol
from xml.etree import ElementTree

import fitz  # type: ignore[import-untyped]

from backend.core.errors import ErrorCode, ProjectError
from backend.core.ports.document_processing import OfficeDocumentAdapter
from backend.document_processing.docling_adapter import (
    DOCLING_VERSION,
    DoclingBoundingBox,
    DoclingCellCandidate,
    DoclingItemCandidate,
)
from backend.document_processing.office_preflight import OfficePreflight
from backend.document_processing.reconciler import ResultReconciler
from backend.document_processing.schema_v2 import (
    AdapterParseResult,
    CanonicalBoundingBox,
    CanonicalDocumentV2,
    CanonicalPage,
    CoordinateSpace,
    DocumentElement,
    DocumentRoutePlan,
    ElementType,
    LocatorType,
    NormalizedBoundingBox,
    PageProfile,
    PageQuality,
    PageSelection,
    ParseRoute,
    ParserProvenance,
    ParsingContext,
    PipelineComponent,
    PipelineDescriptor,
    QualityStatus,
    RouteDecision,
    normalize_element_text,
    stable_element_id,
)
from backend.document_processing.vlm_contract import (
    DocumentVLMProvider,
    VLMContentKind,
    VLMElementCandidate,
    VLMPageRequest,
    VLMResponseStatus,
)


@dataclass(frozen=True, slots=True)
class OfficeEmbeddedImageCandidate:
    image_id: str
    locator_number: int
    image_bytes: bytes
    image_width: int
    image_height: int
    bbox: DoclingBoundingBox


@dataclass(frozen=True, slots=True)
class OfficeVLMItemCandidate:
    item_id: str
    locator_number: int
    element: VLMElementCandidate
    bbox: DoclingBoundingBox
    model_name: str
    model_version: str


@dataclass(frozen=True, slots=True)
class OfficeBackendResult:
    items: tuple[DoclingItemCandidate, ...]
    locator_count: int
    locator_sizes: dict[int, tuple[float, float]]
    warnings: tuple[str, ...] = ()
    failed_locators: tuple[int, ...] = ()
    embedded_images: tuple[OfficeEmbeddedImageCandidate, ...] = ()
    vlm_items: tuple[OfficeVLMItemCandidate, ...] = ()


class OfficeDoclingBackend(Protocol):
    def convert(
        self, file_data: bytes, filename: str, timeout_seconds: float
    ) -> OfficeBackendResult: ...


class LocalDoclingOfficeBackend:
    """Pinned Docling Slim runtime; network relationships are rejected in preflight."""

    def convert(
        self, file_data: bytes, filename: str, timeout_seconds: float
    ) -> OfficeBackendResult:
        try:
            version = importlib.metadata.version("docling-slim")
        except importlib.metadata.PackageNotFoundError as exc:
            raise ModuleNotFoundError("Docling optional dependency is not installed") from exc
        if version != DOCLING_VERSION:
            raise RuntimeError(f"Unsupported docling-slim {version}; expected {DOCLING_VERSION}")
        base_models = importlib.import_module("docling.datamodel.base_models")
        converter_module = importlib.import_module("docling.document_converter")
        suffix = filename.casefold().rsplit(".", 1)[-1]
        input_format = (
            base_models.InputFormat.DOCX if suffix == "docx" else base_models.InputFormat.PPTX
        )
        converter = converter_module.DocumentConverter(allowed_formats=[input_format])
        conversion = converter.convert(
            base_models.DocumentStream(name=filename, stream=BytesIO(file_data)),
            raises_on_error=False,
            max_file_size=len(file_data),
        )
        normalized = _normalize_office_conversion(conversion, suffix, timeout_seconds)
        return replace(
            normalized,
            embedded_images=_extract_office_images(
                file_data,
                suffix,
                normalized.locator_sizes,
            ),
        )


class DoclingOfficeAdapter(OfficeDocumentAdapter):
    name = "docling-office-v2"
    version = "2.0.0"
    model_name = "docling-native-office"
    model_version = DOCLING_VERSION

    def __init__(
        self,
        *,
        backend: OfficeDoclingBackend | None = None,
        preflight: OfficePreflight | None = None,
        reconciler: ResultReconciler | None = None,
        vlm_provider: DocumentVLMProvider | None = None,
        timeout_seconds: float = 120.0,
        max_vlm_images: int = 10,
    ) -> None:
        self._backend = backend or LocalDoclingOfficeBackend()
        self._preflight = preflight or OfficePreflight()
        self._reconciler = reconciler or ResultReconciler()
        self._vlm_provider = vlm_provider
        self._timeout_seconds = timeout_seconds
        self._max_vlm_images = max_vlm_images

    async def supports_format(self, filename: str) -> bool:
        return filename.casefold().endswith((".docx", ".pptx"))

    async def parse(
        self,
        file_data: bytes,
        filename: str,
        *,
        context: ParsingContext,
    ) -> CanonicalDocumentV2:
        if not await self.supports_format(filename):
            raise ProjectError(ErrorCode.UNSAFE_FILE_TYPE, "Docling Office Adapter requires DOCX/PPTX")
        preflight = self._preflight.inspect(file_data, filename)
        if preflight.checksum != context.document_checksum:
            raise ProjectError(
                ErrorCode.FAILED_PRECONDITION,
                "Parser context checksum does not match Office bytes",
            )
        timeout = min(context.timeout_seconds, self._timeout_seconds)
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(self._backend.convert, file_data, filename, timeout),
                timeout=timeout,
            )
        except TimeoutError as exc:
            raise ProjectError(ErrorCode.PARSING_FAILED, "Docling Office parsing timed out") from exc
        except ModuleNotFoundError as exc:
            raise ProjectError(
                ErrorCode.PARSING_FAILED,
                "Docling Office dependency is unavailable",
                details={"reason": "docling_dependency_unavailable"},
            ) from exc
        self._validate_result(result)
        result = await self._enrich_embedded_images(result, context)
        descriptor = PipelineDescriptor(
            router_version="office-native-v1",
            render_scale=1,
            components=(
                PipelineComponent(
                    name=self.name,
                    version=self.version,
                    model_name=self.model_name,
                    model_version=self.model_version,
                ),
            ),
            config={"locator_type": preflight.locator_type.value, "vlm_enabled": False},
        )
        pages = self._pages(result, preflight.checksum, preflight.locator_type)
        selection = PageSelection(page_numbers=tuple(range(1, result.locator_count + 1)))
        adapter_result = AdapterParseResult(
            parser_name=self.name,
            parser_version=self.version,
            selection=selection,
            pages=pages,
            warnings=result.warnings,
            failed_pages=result.failed_locators,
            model_name=self.model_name,
            model_version=self.model_version,
        )
        route_plan = DocumentRoutePlan(
            document_route=ParseRoute.LAYOUT_NATIVE,
            decisions=tuple(
                RouteDecision(
                    page_number=number,
                    route=ParseRoute.LAYOUT_NATIVE,
                    reasons=("native_office_structure", preflight.locator_type.value),
                )
                for number in range(1, result.locator_count + 1)
            ),
            vlm_page_count=0,
            vlm_page_limit=0,
        )
        document = self._reconciler.reconcile(
            filename=filename,
            checksum=preflight.checksum,
            pipeline=descriptor,
            route_plan=route_plan,
            native=adapter_result,
        )
        return document.model_copy(update={"document_locator_type": preflight.locator_type})

    async def _enrich_embedded_images(
        self,
        result: OfficeBackendResult,
        context: ParsingContext,
    ) -> OfficeBackendResult:
        if not result.embedded_images or self._vlm_provider is None:
            return result
        native_text = {
            (item.subset_page_number, normalize_element_text(item.text))
            for item in result.items
            if normalize_element_text(item.text)
        }
        vlm_items: list[OfficeVLMItemCandidate] = []
        warnings = list(result.warnings)
        for image_number, image in enumerate(result.embedded_images[: self._max_vlm_images]):
            request = VLMPageRequest(
                request_id=f"{context.trace_id}:office-image:{image_number}",
                trace_id=context.trace_id,
                page_number=image.locator_number,
                image_bytes=image.image_bytes,
                image_width=image.image_width,
                image_height=image.image_height,
                allowed_element_types=tuple(
                    item
                    for item in ElementType
                    if item not in {ElementType.TEXT_LINE, ElementType.TEXT_SPAN, ElementType.UNKNOWN}
                ),
            )
            try:
                response = await self._vlm_provider.infer(
                    request,
                    timeout_seconds=min(context.timeout_seconds, self._timeout_seconds),
                )
            except (TimeoutError, OSError):
                warnings.append(f"locator_{image.locator_number}:office_image_vlm_unavailable")
                continue
            if response.status is not VLMResponseStatus.SUCCESS:
                warnings.append(
                    f"locator_{image.locator_number}:office_image_vlm_{response.status.value}"
                )
                continue
            for element_number, element in enumerate(response.elements):
                normalized = normalize_element_text(element.text)
                if normalized and (image.locator_number, normalized) in native_text:
                    continue
                vlm_items.append(
                    OfficeVLMItemCandidate(
                        item_id=f"{image.image_id}/vlm/{element_number}",
                        locator_number=image.locator_number,
                        element=element,
                        bbox=_map_pixel_box_to_office(element, image),
                        model_name=response.model_name,
                        model_version=response.model_version,
                    )
                )
        return replace(
            result,
            warnings=tuple(dict.fromkeys(warnings)),
            vlm_items=tuple(vlm_items),
        )

    @staticmethod
    def _validate_result(result: OfficeBackendResult) -> None:
        expected = set(range(1, result.locator_count + 1))
        if result.locator_count < 1 or set(result.locator_sizes) != expected:
            raise ProjectError(ErrorCode.PARSING_FAILED, "Invalid Office locator map")
        if not set(result.failed_locators) <= expected:
            raise ProjectError(ErrorCode.PARSING_FAILED, "Invalid failed Office locator")
        if any(item.subset_page_number not in expected for item in result.items):
            raise ProjectError(ErrorCode.PARSING_FAILED, "Office item references unknown locator")
        if any(item.locator_number not in expected for item in result.vlm_items):
            raise ProjectError(ErrorCode.PARSING_FAILED, "Office VLM item references unknown locator")

    def _pages(
        self,
        result: OfficeBackendResult,
        checksum: str,
        locator_type: LocatorType,
    ) -> tuple[CanonicalPage, ...]:
        grouped: dict[int, list[DoclingItemCandidate]] = defaultdict(list)
        for native_item in result.items:
            grouped[native_item.subset_page_number].append(native_item)
        grouped_vlm: dict[int, list[OfficeVLMItemCandidate]] = defaultdict(list)
        for vlm_item in result.vlm_items:
            grouped_vlm[vlm_item.locator_number].append(vlm_item)
        return tuple(
            self._page(
                number,
                grouped[number],
                grouped_vlm[number],
                result.locator_sizes[number],
                checksum,
                locator_type,
                failed=number in result.failed_locators,
            )
            for number in range(1, result.locator_count + 1)
        )

    def _page(
        self,
        number: int,
        items: list[DoclingItemCandidate],
        vlm_items: list[OfficeVLMItemCandidate],
        size: tuple[float, float],
        checksum: str,
        locator_type: LocatorType,
        *,
        failed: bool,
    ) -> CanonicalPage:
        width, height = size
        elements: list[DocumentElement] = []
        for order, item in enumerate(sorted(items, key=lambda value: value.reading_order)):
            bbox = _bounded_box(item.bbox, width, height)
            element_type = _element_type(item.label)
            elements.append(
                DocumentElement(
                    element_id=stable_element_id(checksum, number, element_type, order, bbox, item.text),
                    page_number=number,
                    element_type=element_type,
                    text=item.text,
                    normalized_text=normalize_element_text(item.text),
                    bbox=bbox,
                    normalized_bbox=_normalized_box(bbox, width, height),
                    reading_order=order,
                    provenance=ParserProvenance(
                        parser_name=self.name,
                        parser_version=self.version,
                        model_name=self.model_name,
                        model_version=self.model_version,
                        confidence=max(0.0, min(1.0, item.confidence)),
                        source_coordinate_space=CoordinateSpace.OFFICE_LAYOUT,
                    ),
                    metadata={
                        "locator_type": locator_type.value,
                        "locator_index": number,
                        "docling_item_id": item.item_id,
                        "content_layer": item.content_layer,
                    },
                )
            )
        native_by_item_id = {
            item.item_id: elements[index]
            for index, item in enumerate(
                sorted(items, key=lambda value: value.reading_order)
            )
        }
        element_index = {
            element.element_id: index for index, element in enumerate(elements)
        }
        for native_item in sorted(items, key=lambda value: value.reading_order):
            parent = native_by_item_id[native_item.item_id]
            child_ids: list[str] = []
            for cell_number, cell in enumerate(native_item.cells):
                order = len(elements)
                cell_bbox = _bounded_box(cell.bbox, width, height)
                cell_id = stable_element_id(
                    checksum,
                    number,
                    ElementType.TABLE_CELL,
                    order,
                    cell_bbox,
                    cell.text,
                )
                child_ids.append(cell_id)
                elements.append(
                    DocumentElement(
                        element_id=cell_id,
                        page_number=number,
                        element_type=ElementType.TABLE_CELL,
                        text=cell.text,
                        normalized_text=normalize_element_text(cell.text),
                        bbox=cell_bbox,
                        normalized_bbox=_normalized_box(cell_bbox, width, height),
                        reading_order=order,
                        provenance=ParserProvenance(
                            parser_name=self.name,
                            parser_version=self.version,
                            model_name=self.model_name,
                            model_version=self.model_version,
                            confidence=max(0.0, min(1.0, cell.confidence)),
                            source_coordinate_space=CoordinateSpace.OFFICE_LAYOUT,
                        ),
                        parent_id=parent.element_id,
                        metadata={
                            "locator_type": locator_type.value,
                            "locator_index": number,
                            "row_index": cell.row_index,
                            "column_index": cell.column_index,
                            "row_span": cell.row_span,
                            "column_span": cell.column_span,
                            "docling_cell_number": cell_number,
                        },
                    )
                )
            if child_ids:
                index = element_index[parent.element_id]
                elements[index] = parent.model_copy(
                    update={"children_ids": tuple(child_ids)}
                )
        for vlm_item in sorted(
            vlm_items,
            key=lambda value: (value.element.reading_order, value.item_id),
        ):
            order = len(elements)
            bbox = _bounded_box(vlm_item.bbox, width, height)
            inferred = (
                vlm_item.element.content_kind is VLMContentKind.GENERATED_DESCRIPTION
            )
            elements.append(
                DocumentElement(
                    element_id=stable_element_id(
                        checksum,
                        number,
                        vlm_item.element.element_type,
                        order,
                        bbox,
                        vlm_item.element.text,
                    ),
                    page_number=number,
                    element_type=vlm_item.element.element_type,
                    text=vlm_item.element.text,
                    normalized_text=normalize_element_text(vlm_item.element.text),
                    bbox=bbox,
                    normalized_bbox=_normalized_box(bbox, width, height),
                    reading_order=order,
                    provenance=ParserProvenance(
                        parser_name="paddleocr-vl-office-region",
                        parser_version="2.0.0",
                        model_name=vlm_item.model_name,
                        model_version=vlm_item.model_version,
                        confidence=vlm_item.element.confidence,
                        source_coordinate_space=CoordinateSpace.OFFICE_LAYOUT,
                        is_inferred=inferred,
                        warnings=vlm_item.element.warnings,
                    ),
                    is_inferred=inferred,
                    metadata={
                        "locator_type": locator_type.value,
                        "locator_index": number,
                        "office_image_region": True,
                        "content_kind": vlm_item.element.content_kind.value,
                    },
                )
            )
        score = sum(item.provenance.confidence for item in elements) / len(elements) if elements else 0
        warnings = ("docling_office_locator_failed",) if failed else (() if elements else ("empty_office_locator",))
        quality_status = QualityStatus.FAILED if failed or not elements else QualityStatus.PASS
        profile = PageProfile(
            page_number=number,
            native_character_count=sum(len(item.text) for item in elements),
            garble_ratio=0,
            image_coverage=0,
            text_overlap_ratio=0,
            bbox_out_of_bounds_ratio=0,
            detected_column_count=1,
            proposed_route=ParseRoute.LAYOUT_NATIVE,
            route_reasons=("native_office_structure", locator_type.value),
        )
        return CanonicalPage(
            page_number=number,
            width=width,
            height=height,
            rotation=0,
            cropbox=CanonicalBoundingBox(x0=0, y0=0, x1=width, y1=height),
            selected_route=ParseRoute.LAYOUT_NATIVE,
            route_reasons=profile.route_reasons,
            profile=profile,
            elements=tuple(elements),
            quality=PageQuality(
                status=quality_status,
                overall=score,
                text=score,
                coordinates=1,
                reading_order=score,
                structure=score,
                ocr=1,
                tables=1,
                completeness=score,
                warnings=warnings,
            ),
        )


def _map_pixel_box_to_office(
    element: VLMElementCandidate,
    image: OfficeEmbeddedImageCandidate,
) -> DoclingBoundingBox:
    source = element.bbox
    width = max(1, image.image_width)
    height = max(1, image.image_height)
    region_width = image.bbox.right - image.bbox.left
    region_height = image.bbox.bottom - image.bbox.top
    return DoclingBoundingBox(
        left=image.bbox.left + source.x0 / width * region_width,
        top=image.bbox.top + source.y0 / height * region_height,
        right=image.bbox.left + source.x1 / width * region_width,
        bottom=image.bbox.top + source.y1 / height * region_height,
    )


def _extract_office_images(
    file_data: bytes,
    suffix: str,
    locator_sizes: dict[int, tuple[float, float]],
) -> tuple[OfficeEmbeddedImageCandidate, ...]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(file_data))
    except zipfile.BadZipFile:
        return ()
    with archive:
        names = set(archive.namelist())
        references = (
            _pptx_image_references(archive, names)
            if suffix == "pptx"
            else _docx_image_references(archive, names)
        )
        result: list[OfficeEmbeddedImageCandidate] = []
        seen: set[tuple[int, str]] = set()
        for locator, target in references:
            if locator not in locator_sizes or target not in names or (locator, target) in seen:
                continue
            seen.add((locator, target))
            image_bytes = archive.read(target)
            dimensions = _image_size(image_bytes)
            if dimensions is None:
                continue
            width, height = locator_sizes[locator]
            result.append(
                OfficeEmbeddedImageCandidate(
                    image_id=f"{locator}:{target}",
                    locator_number=locator,
                    image_bytes=image_bytes,
                    image_width=dimensions[0],
                    image_height=dimensions[1],
                    bbox=DoclingBoundingBox(
                        left=20,
                        top=100,
                        right=max(20, width - 20),
                        bottom=max(100, height - 20),
                    ),
                )
            )
        return tuple(result[:10])


def _pptx_image_references(
    archive: zipfile.ZipFile,
    names: set[str],
) -> list[tuple[int, str]]:
    result: list[tuple[int, str]] = []
    for slide_path in sorted(
        name
        for name in names
        if name.startswith("ppt/slides/slide") and name.endswith(".xml")
    ):
        stem = slide_path.removesuffix(".xml").rsplit("slide", 1)[-1]
        if not stem.isdigit():
            continue
        rels_path = f"ppt/slides/_rels/slide{stem}.xml.rels"
        if rels_path not in names:
            continue
        for relationship in _relationships(archive.read(rels_path)):
            if str(relationship.get("Type", "")).endswith("/image"):
                target = posixpath.normpath(
                    posixpath.join(posixpath.dirname(slide_path), relationship["Target"])
                )
                result.append((int(stem), target))
    return result


def _docx_image_references(
    archive: zipfile.ZipFile,
    names: set[str],
) -> list[tuple[int, str]]:
    rels_path = "word/_rels/document.xml.rels"
    if rels_path not in names:
        return []
    relationships = {
        item["Id"]: posixpath.normpath(posixpath.join("word", item["Target"]))
        for item in _relationships(archive.read(rels_path))
        if str(item.get("Type", "")).endswith("/image")
    }
    if not relationships:
        return []
    try:
        root = ElementTree.fromstring(archive.read("word/document.xml"))
    except ElementTree.ParseError:
        return []
    result: list[tuple[int, str]] = []
    position = 0
    for node in root.iter():
        if not node.tag.endswith("}p"):
            continue
        position += 1
        for descendant in node.iter():
            relation_id = next(
                (
                    value
                    for key, value in descendant.attrib.items()
                    if key.endswith("}embed")
                ),
                None,
            )
            if relation_id in relationships:
                result.append((position, relationships[relation_id]))
    return result


def _relationships(data: bytes) -> list[dict[str, str]]:
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError:
        return []
    return [dict(node.attrib) for node in root.iter() if node.tag.endswith("Relationship")]


def _image_size(data: bytes) -> tuple[int, int] | None:
    try:
        pixmap = fitz.Pixmap(data)
    except Exception:
        return None
    return pixmap.width, pixmap.height


def _normalize_office_conversion(conversion: Any, suffix: str, timeout_seconds: float) -> OfficeBackendResult:
    del timeout_seconds
    document = conversion.document
    items: list[DoclingItemCandidate] = []
    sizes: dict[int, tuple[float, float]] = {}
    current_docx_position = 0
    for reading_order, (item, level) in enumerate(document.iterate_items()):
        text = str(getattr(item, "text", "") or "")
        if not text and not getattr(item, "data", None):
            continue
        provenance = tuple(getattr(item, "prov", ()) or ())
        if suffix == "docx":
            current_docx_position += 1
            locator = current_docx_position
        else:
            locator = int(getattr(provenance[0], "page_no", 1)) if provenance else 1
        bbox_value = getattr(provenance[0], "bbox", None) if provenance else None
        bbox = _docling_box_or_default(bbox_value)
        sizes.setdefault(locator, (960.0, 540.0) if suffix == "pptx" else (720.0, 1_000.0))
        items.append(
            DoclingItemCandidate(
                item_id=str(getattr(item, "self_ref", f"item-{reading_order}")),
                subset_page_number=locator,
                label=str(getattr(getattr(item, "label", "paragraph"), "value", getattr(item, "label", "paragraph"))),
                content_layer=str(getattr(getattr(item, "content_layer", "body"), "value", "body")),
                text=text,
                bbox=bbox,
                reading_order=reading_order,
                hierarchy_level=int(level),
                confidence=0.9,
                cells=_office_cells(item),
            )
        )
    locator_count = max(sizes, default=0)
    if locator_count < 1:
        raise ProjectError(ErrorCode.PARSING_FAILED, "Docling returned no Office content")
    for locator in range(1, locator_count + 1):
        sizes.setdefault(locator, (960.0, 540.0) if suffix == "pptx" else (720.0, 1_000.0))
    return OfficeBackendResult(items=tuple(items), locator_count=locator_count, locator_sizes=sizes)


def _office_cells(item: Any) -> tuple[DoclingCellCandidate, ...]:
    result: list[DoclingCellCandidate] = []
    for cell in getattr(getattr(item, "data", None), "table_cells", ()):
        result.append(
            DoclingCellCandidate(
                row_index=int(getattr(cell, "start_row_offset_idx", 0)),
                column_index=int(getattr(cell, "start_col_offset_idx", 0)),
                row_span=max(1, int(getattr(cell, "row_span", 1))),
                column_span=max(1, int(getattr(cell, "col_span", 1))),
                text=str(getattr(cell, "text", "")),
                bbox=_docling_box_or_default(getattr(cell, "bbox", None)),
                confidence=0.9,
            )
        )
    return tuple(result)


def _docling_box_or_default(value: Any) -> DoclingBoundingBox:
    if value is None:
        return DoclingBoundingBox(20, 20, 700, 80)
    return DoclingBoundingBox(
        float(value.l),
        float(value.t),
        float(value.r),
        float(value.b),
        "bottom_left" if "bottom" in str(getattr(value, "coord_origin", "")).casefold() else "top_left",
    )


def _bounded_box(value: DoclingBoundingBox, width: float, height: float) -> CanonicalBoundingBox:
    x0, x1 = sorted((max(0.0, min(width, value.left)), max(0.0, min(width, value.right))))
    y0, y1 = sorted((max(0.0, min(height, value.top)), max(0.0, min(height, value.bottom))))
    return CanonicalBoundingBox(x0=x0, y0=y0, x1=x1, y1=y1)


def _normalized_box(
    value: CanonicalBoundingBox, width: float, height: float
) -> NormalizedBoundingBox:
    return NormalizedBoundingBox(
        x0=value.x0 / width,
        y0=value.y0 / height,
        x1=value.x1 / width,
        y1=value.y1 / height,
    )


def _element_type(label: str) -> ElementType:
    return {
        "title": ElementType.TITLE,
        "section_header": ElementType.SECTION_HEADING,
        "paragraph": ElementType.PARAGRAPH,
        "text": ElementType.PARAGRAPH,
        "list_item": ElementType.LIST_ITEM,
        "caption": ElementType.CAPTION,
        "table": ElementType.TABLE,
        "picture": ElementType.FIGURE,
        "chart": ElementType.FIGURE,
        "formula": ElementType.EQUATION,
        "code": ElementType.CODE,
    }.get(label.casefold(), ElementType.UNKNOWN)
