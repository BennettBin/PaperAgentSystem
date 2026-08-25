"""Bounded PaddleOCR-VL service Adapter producing V2 page candidates."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import ipaddress
import math
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlparse

import fitz  # type: ignore[import-untyped]
import httpx

from backend.core.errors import ErrorCode, ProjectError
from backend.core.ports.document_processing import DocumentVLMAdapter
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
    stable_identifier,
)
from backend.document_processing.vlm_contract import (
    DocumentVLMProvider,
    PixelBoundingBox,
    VLMContentKind,
    VLMElementCandidate,
    VLMPageRequest,
    VLMPageResponse,
    VLMResponseStatus,
)

ALLOWED_VLM_ELEMENTS = tuple(
    element_type
    for element_type in ElementType
    if element_type
    not in {ElementType.TEXT_LINE, ElementType.TEXT_SPAN, ElementType.UNKNOWN}
)
STATUS_WARNING = {
    VLMResponseStatus.SERVICE_UNAVAILABLE: "vlm_service_unavailable",
    VLMResponseStatus.TIMEOUT: "vlm_timeout",
    VLMResponseStatus.OOM: "vlm_oom",
    VLMResponseStatus.INVALID_RESPONSE: "vlm_invalid_response",
    VLMResponseStatus.FATAL_ERROR: "vlm_fatal_error",
}
RETRYABLE_STATUSES = {
    VLMResponseStatus.SERVICE_UNAVAILABLE,
    VLMResponseStatus.TIMEOUT,
}


class OCRLineLike(Protocol):
    text: str
    confidence: float
    bbox: tuple[float, float, float, float]


class OCREngineLike(Protocol):
    name: str

    async def recognize(
        self,
        image: bytes,
        page_number: int,
    ) -> list[OCRLineLike]: ...


class CPUOCRV2Provider:
    """Wrap a legacy CPU OCR engine behind the V2 VLM provider contract."""

    def __init__(self, engine: OCREngineLike) -> None:
        self._engine = engine

    async def infer(
        self,
        request: VLMPageRequest,
        *,
        timeout_seconds: float,
    ) -> VLMPageResponse:
        lines = await asyncio.wait_for(
            self._engine.recognize(request.image_bytes, request.page_number),
            timeout=timeout_seconds,
        )
        return VLMPageResponse(
            request_id=request.request_id,
            page_number=request.page_number,
            status=VLMResponseStatus.SUCCESS,
            model_name=self._engine.name,
            model_version="cpu-v2",
            elements=tuple(
                VLMElementCandidate(
                    element_type=ElementType.PARAGRAPH,
                    text=line.text,
                    original_text=line.text,
                    bbox=PixelBoundingBox(
                        x0=line.bbox[0],
                        y0=line.bbox[1],
                        x1=line.bbox[2],
                        y1=line.bbox[3],
                    ),
                    reading_order=index,
                    confidence=line.confidence,
                )
                for index, line in enumerate(lines)
            ),
        )


class InternalHTTPDocumentVLMProvider:
    """Client for the internal provider-neutral gateway in front of PaddleOCR-VL."""

    def __init__(
        self,
        endpoint: str,
        *,
        allowed_hosts: tuple[str, ...] = (),
        bearer_token: str | None = None,
        max_response_bytes: int = 10 * 1024 * 1024,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.endpoint = _validate_internal_endpoint(endpoint, allowed_hosts)
        self._bearer_token = bearer_token
        self._max_response_bytes = max_response_bytes
        self._client = client

    async def infer(
        self,
        request: VLMPageRequest,
        *,
        timeout_seconds: float,
    ) -> VLMPageResponse:
        headers = {"Content-Type": "application/json"}
        if self._bearer_token:
            headers["Authorization"] = f"Bearer {self._bearer_token}"
        payload = {
            "request_id": request.request_id,
            "trace_id": request.trace_id,
            "page_number": request.page_number,
            "image_base64": base64.b64encode(request.image_bytes).decode("ascii"),
            "image_width": request.image_width,
            "image_height": request.image_height,
            "expected_languages": list(request.expected_languages),
            "allowed_element_types": [value.value for value in request.allowed_element_types],
            "document_content_is_untrusted": True,
        }
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient()
        try:
            response = await client.post(
                self.endpoint,
                json=payload,
                headers=headers,
                timeout=timeout_seconds,
            )
            response.raise_for_status()
            if len(response.content) > self._max_response_bytes:
                raise ValueError("document VLM response exceeds configured byte limit")
            return VLMPageResponse.model_validate(response.json())
        finally:
            if owns_client:
                await client.aclose()


@dataclass(frozen=True, slots=True)
class _RenderedPage:
    page_number: int
    image_bytes: bytes
    image_width: int
    image_height: int
    transformer: CoordinateTransformer
    profile: PageProfile


@dataclass(frozen=True, slots=True)
class _PageOutcome:
    rendered: _RenderedPage
    response: VLMPageResponse | None
    warnings: tuple[str, ...]
    failed_reason: str | None = None
    service_calls: int = 0
    fallback_count: int = 0


@dataclass(frozen=True, slots=True)
class _ElementDraft:
    key: str
    parent_key: str | None
    element_type: ElementType
    text: str
    bbox: CanonicalBoundingBox
    confidence: float
    inferred: bool
    model_name: str
    model_version: str
    metadata: dict[str, str | int | float | bool | None]
    warnings: tuple[str, ...]


class PaddleOCRVLAdapter(DocumentVLMAdapter):
    name = "paddleocr-vl-v2"
    version = "2.0.0"
    model_name = "PaddleOCR-VL-1.6-0.9B"
    model_version = "1.6"

    def __init__(
        self,
        config: DocumentProcessingConfig | None = None,
        *,
        provider: DocumentVLMProvider | None = None,
        cpu_fallback_provider: DocumentVLMProvider | None = None,
        profiler: PageProfiler | None = None,
        router: DeterministicParseRouter | None = None,
    ) -> None:
        self._config = config or DocumentProcessingConfig()
        self._provider = provider
        self._cpu_fallback = cpu_fallback_provider
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
            raise ProjectError(ErrorCode.PARSING_FAILED, "PaddleOCR-VL Adapter requires a PDF")
        checksum = hashlib.sha256(file_data).hexdigest()
        if checksum != context.document_checksum:
            raise ProjectError(
                ErrorCode.FAILED_PRECONDITION,
                "Parser context checksum does not match PDF bytes",
                details={"reason": "document_checksum_mismatch"},
            )
        started = time.perf_counter()
        if self._provider is None and self._cpu_fallback is None:
            self._validate_pdf_selection(file_data, selection)
            return self._all_failed(
                selection,
                started,
                "vlm_service_unconfigured",
            )
        rendered_pages, blocked_pages = self._render_selected_pages(file_data, selection)

        outcomes: list[_PageOutcome] = []
        semaphore = asyncio.Semaphore(self._config.vlm_max_concurrency)
        for start in range(0, len(rendered_pages), self._config.vlm_batch_size):
            batch = rendered_pages[start : start + self._config.vlm_batch_size]
            outcomes.extend(
                await asyncio.gather(
                    *(
                        self._process_page(
                            rendered,
                            checksum=checksum,
                            context=context,
                            semaphore=semaphore,
                        )
                        for rendered in batch
                    )
                )
            )

        pages: list[CanonicalPage] = []
        failed_pages = list(blocked_pages)
        result_warnings = [
            f"page_{page}:vlm_page_budget_exceeded" for page in blocked_pages
        ]
        used_models: set[tuple[str, str]] = set()
        for outcome in outcomes:
            if outcome.response is None or outcome.failed_reason is not None:
                failed_pages.append(outcome.rendered.page_number)
                reason = outcome.failed_reason or "vlm_invalid_response"
                result_warnings.append(
                    f"page_{outcome.rendered.page_number}:{reason}"
                )
                continue
            try:
                page = self._map_page(outcome, checksum)
            except ValueError:
                failed_pages.append(outcome.rendered.page_number)
                result_warnings.append(
                    f"page_{outcome.rendered.page_number}:vlm_invalid_response"
                )
                continue
            pages.append(page)
            used_models.add(
                (outcome.response.model_name, outcome.response.model_version)
            )
        model_name, model_version = _result_model(used_models, self)
        return AdapterParseResult(
            parser_name=self.name,
            parser_version=self.version,
            selection=selection,
            pages=tuple(sorted(pages, key=lambda page: page.page_number)),
            warnings=tuple(dict.fromkeys(result_warnings)),
            failed_pages=tuple(sorted(failed_pages)),
            model_name=model_name,
            model_version=model_version,
            duration_ms=_elapsed_ms(started),
            metrics={
                "vlm_page_count": len(selection.page_numbers),
                "rendered_pixel_count": sum(
                    item.rendered.image_width * item.rendered.image_height
                    for item in outcomes
                ),
                "service_call_count": sum(item.service_calls for item in outcomes),
                "fallback_count": sum(item.fallback_count for item in outcomes),
            },
        )

    @staticmethod
    def _validate_pdf_selection(file_data: bytes, selection: PageSelection) -> None:
        try:
            document = fitz.open(stream=file_data, filetype="pdf")
        except Exception as exc:
            raise ProjectError(ErrorCode.PARSING_FAILED, "Invalid PDF document", cause=exc) from exc
        try:
            if any(page > document.page_count for page in selection.page_numbers):
                raise ProjectError(
                    ErrorCode.OUT_OF_RANGE,
                    "Selected PDF page is outside the document",
                )
        finally:
            document.close()

    def _render_selected_pages(
        self,
        file_data: bytes,
        selection: PageSelection,
    ) -> tuple[list[_RenderedPage], tuple[int, ...]]:
        try:
            document = fitz.open(stream=file_data, filetype="pdf")
        except Exception as exc:
            raise ProjectError(ErrorCode.PARSING_FAILED, "Invalid PDF document", cause=exc) from exc
        allowed_pages = selection.page_numbers[: self._config.vlm_max_pages_per_document]
        blocked_pages = selection.page_numbers[self._config.vlm_max_pages_per_document :]
        rendered: list[_RenderedPage] = []
        try:
            if any(page > document.page_count for page in selection.page_numbers):
                raise ProjectError(
                    ErrorCode.OUT_OF_RANGE,
                    "Selected PDF page is outside the document",
                )
            for page_number in allowed_pages:
                page = document[page_number - 1]
                transformer = CoordinateTransformer.from_page(page, render_scale=1)
                page_pixel_limit = min(
                    self._config.vlm_max_render_pixels_per_page,
                    self._config.max_render_pixels_per_page,
                )
                scale = _bounded_render_scale(
                    transformer.page_width,
                    transformer.page_height,
                    preferred_scale=self._config.render_scale,
                    max_long_edge=self._config.vlm_max_long_edge_pixels,
                    max_pixels=page_pixel_limit,
                )
                pixmap, scale = _render_with_hard_limits(
                    page,
                    scale=scale,
                    max_long_edge=self._config.vlm_max_long_edge_pixels,
                    max_pixels=page_pixel_limit,
                )
                routed_profile = self._router.profile(
                    self._profiler.profile_page(page, page_number)
                )
                profile = routed_profile.model_copy(
                    update={
                        "proposed_route": ParseRoute.DOCUMENT_VLM,
                        "route_reasons": tuple(
                            dict.fromkeys(
                                (*routed_profile.route_reasons, "document_vlm_candidate")
                            )
                        ),
                    }
                )
                rendered.append(
                    _RenderedPage(
                        page_number=page_number,
                        image_bytes=pixmap.tobytes("png"),
                        image_width=pixmap.width,
                        image_height=pixmap.height,
                        transformer=transformer,
                        profile=profile,
                    )
                )
            return rendered, blocked_pages
        finally:
            document.close()

    async def _process_page(
        self,
        rendered: _RenderedPage,
        *,
        checksum: str,
        context: ParsingContext,
        semaphore: asyncio.Semaphore,
    ) -> _PageOutcome:
        expected_language = context.metadata.get("expected_language", "und")
        languages = (
            (expected_language,)
            if isinstance(expected_language, str)
            else ("und",)
        )
        request = VLMPageRequest(
            request_id=stable_identifier(
                "vlmreq",
                checksum,
                rendered.page_number,
                context.trace_id,
                rendered.image_width,
                rendered.image_height,
            ),
            trace_id=context.trace_id,
            page_number=rendered.page_number,
            image_bytes=rendered.image_bytes,
            image_width=rendered.image_width,
            image_height=rendered.image_height,
            expected_languages=languages,
            allowed_element_types=ALLOWED_VLM_ELEMENTS,
        )
        timeout = min(context.timeout_seconds, self._config.vlm_timeout_seconds)
        response, warnings, failed_reason, service_calls = await self._infer_bounded(
            self._provider,
            request,
            timeout,
            semaphore,
        )
        if failed_reason is not None and self._cpu_fallback is not None:
            fallback, fallback_warnings, fallback_failure, fallback_calls = await self._infer_bounded(
                self._cpu_fallback,
                request,
                timeout,
                semaphore,
                retries=0,
            )
            if fallback_failure is None:
                response = fallback
                warnings = tuple(
                    dict.fromkeys(
                        (*warnings, *fallback_warnings, "vlm_cpu_fallback_used")
                    )
                )
                failed_reason = None
            service_calls += fallback_calls
            fallback_count = 1
        else:
            fallback_count = 0
        return _PageOutcome(
            rendered=rendered,
            response=response,
            warnings=warnings,
            failed_reason=failed_reason,
            service_calls=service_calls,
            fallback_count=fallback_count,
        )

    async def _infer_bounded(
        self,
        provider: DocumentVLMProvider | None,
        request: VLMPageRequest,
        timeout: float,
        semaphore: asyncio.Semaphore,
        *,
        retries: int | None = None,
    ) -> tuple[VLMPageResponse | None, tuple[str, ...], str | None, int]:
        if provider is None:
            return None, ("vlm_service_unconfigured",), "vlm_service_unconfigured", 0
        maximum_retries = self._config.vlm_max_retries if retries is None else retries
        warnings: list[str] = []
        service_calls = 0
        for attempt in range(maximum_retries + 1):
            try:
                async with semaphore:
                    service_calls += 1
                    response = await asyncio.wait_for(
                        provider.infer(request, timeout_seconds=timeout),
                        timeout=timeout,
                    )
            except TimeoutError:
                status = VLMResponseStatus.TIMEOUT
                response = None
            except Exception:
                status = VLMResponseStatus.SERVICE_UNAVAILABLE
                response = None
            else:
                assert response is not None
                if (
                    response.request_id != request.request_id
                    or response.page_number != request.page_number
                ):
                    status = VLMResponseStatus.INVALID_RESPONSE
                else:
                    status = response.status
                    warnings.extend(response.warnings)
                    if status is VLMResponseStatus.SUCCESS:
                        if response.elements:
                            return response, tuple(dict.fromkeys(warnings)), None, service_calls
                        status = VLMResponseStatus.INVALID_RESPONSE
            warning = STATUS_WARNING.get(status, "vlm_fatal_error")
            warnings.append(warning)
            if status not in RETRYABLE_STATUSES or attempt == maximum_retries:
                return response, tuple(dict.fromkeys(warnings)), warning, service_calls
        return None, tuple(dict.fromkeys(warnings)), "vlm_fatal_error", service_calls

    def _map_page(
        self,
        outcome: _PageOutcome,
        checksum: str,
    ) -> CanonicalPage:
        response = outcome.response
        if response is None:
            raise ValueError("successful outcome requires a response")
        rendered = outcome.rendered
        drafts: list[_ElementDraft] = []
        for candidate_index, candidate in enumerate(
            sorted(response.elements, key=lambda item: (item.reading_order, item.element_type.value))
        ):
            if candidate.element_type not in ALLOWED_VLM_ELEMENTS:
                raise ValueError("VLM returned a disallowed element type")
            bbox = _pixel_to_canonical(candidate.bbox, rendered)
            key = f"element/{candidate_index}"
            inferred = candidate.content_kind is VLMContentKind.GENERATED_DESCRIPTION
            metadata: dict[str, str | int | float | bool | None] = {
                "content_kind": candidate.content_kind.value,
                "language": candidate.language,
                "vlm_reading_order": candidate.reading_order,
            }
            if candidate.original_text is not None:
                metadata["original_text"] = candidate.original_text
            if candidate.latex is not None:
                metadata["latex"] = candidate.latex
            drafts.append(
                _ElementDraft(
                    key=key,
                    parent_key=None,
                    element_type=candidate.element_type,
                    text=candidate.text,
                    bbox=bbox,
                    confidence=candidate.confidence,
                    inferred=inferred,
                    model_name=response.model_name,
                    model_version=response.model_version,
                    metadata=metadata,
                    warnings=candidate.warnings,
                )
            )
            for cell_index, cell in enumerate(candidate.cells):
                drafts.append(
                    _ElementDraft(
                        key=f"{key}/cell/{cell_index}",
                        parent_key=key,
                        element_type=ElementType.TABLE_CELL,
                        text=cell.text,
                        bbox=_pixel_to_canonical(cell.bbox, rendered),
                        confidence=cell.confidence,
                        inferred=False,
                        model_name=response.model_name,
                        model_version=response.model_version,
                        metadata={
                            "content_kind": VLMContentKind.OCR_TEXT.value,
                            "row_index": cell.row_index,
                            "column_index": cell.column_index,
                            "row_span": cell.row_span,
                            "column_span": cell.column_span,
                        },
                        warnings=(),
                    )
                )
        identifiers = {
            draft.key: stable_element_id(
                checksum,
                rendered.page_number,
                draft.element_type,
                order,
                draft.bbox,
                draft.text,
            )
            for order, draft in enumerate(drafts)
        }
        children: dict[str, list[str]] = defaultdict(list)
        for draft in drafts:
            if draft.parent_key is not None:
                children[draft.parent_key].append(identifiers[draft.key])
        elements = tuple(
            DocumentElement(
                element_id=identifiers[draft.key],
                page_number=rendered.page_number,
                element_type=draft.element_type,
                text=draft.text,
                normalized_text=normalize_element_text(draft.text),
                bbox=draft.bbox,
                normalized_bbox=rendered.transformer.normalize(draft.bbox),
                reading_order=order,
                provenance=ParserProvenance(
                    parser_name=self.name,
                    parser_version=self.version,
                    model_name=draft.model_name,
                    model_version=draft.model_version,
                    confidence=draft.confidence,
                    source_coordinate_space=CoordinateSpace.RENDER_PIXEL,
                    is_inferred=draft.inferred,
                    warnings=draft.warnings,
                ),
                parent_id=(
                    identifiers[draft.parent_key]
                    if draft.parent_key is not None
                    else None
                ),
                children_ids=tuple(children[draft.key]),
                is_inferred=draft.inferred,
                metadata=draft.metadata,
            )
            for order, draft in enumerate(drafts)
        )
        average_confidence = sum(
            element.provenance.confidence for element in elements
        ) / max(1, len(elements))
        warnings = list(outcome.warnings)
        quality_status = QualityStatus.PASS
        if average_confidence < self._config.vlm_min_confidence:
            warnings.append("vlm_low_confidence")
            quality_status = QualityStatus.FAILED
        table_roots = [item for item in elements if item.element_type is ElementType.TABLE]
        table_cells = [item for item in elements if item.element_type is ElementType.TABLE_CELL]
        return CanonicalPage(
            page_number=rendered.page_number,
            width=rendered.transformer.page_width,
            height=rendered.transformer.page_height,
            rotation=rendered.transformer.rotation,
            cropbox=CanonicalBoundingBox(
                x0=0,
                y0=0,
                x1=rendered.transformer.page_width,
                y1=rendered.transformer.page_height,
            ),
            selected_route=ParseRoute.DOCUMENT_VLM,
            route_reasons=rendered.profile.route_reasons,
            profile=rendered.profile,
            elements=elements,
            quality=PageQuality(
                status=quality_status,
                overall=average_confidence,
                text=average_confidence,
                coordinates=1.0,
                reading_order=average_confidence,
                structure=average_confidence,
                ocr=average_confidence,
                tables=1.0 if not table_roots or table_cells else 0.5,
                completeness=average_confidence,
                warnings=tuple(dict.fromkeys(warnings)),
            ),
        )

    def _all_failed(
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
            metrics={
                "vlm_page_count": len(selection.page_numbers),
                "rendered_pixel_count": 0,
                "service_call_count": 0,
                "fallback_count": 0,
            },
        )


async def parse_vlm_candidates(
    adapter: PaddleOCRVLAdapter,
    file_data: bytes,
    filename: str,
    route_plan: DocumentRoutePlan,
    context: ParsingContext,
) -> AdapterParseResult | None:
    """Invoke the VLM Adapter only for pages selected by the document VLM route."""

    pages = tuple(
        decision.page_number
        for decision in route_plan.decisions
        if decision.route is ParseRoute.DOCUMENT_VLM
    )
    if not pages:
        return None
    return await adapter.parse_pages(
        file_data,
        filename,
        PageSelection(page_numbers=pages),
        context,
    )


def _bounded_render_scale(
    width: float,
    height: float,
    *,
    preferred_scale: float,
    max_long_edge: int,
    max_pixels: int,
) -> float:
    long_edge_scale = max_long_edge / max(width, height)
    pixel_scale = math.sqrt(max_pixels / (width * height))
    return max(0.01, min(preferred_scale, long_edge_scale, pixel_scale))


def _render_with_hard_limits(
    page: fitz.Page,
    *,
    scale: float,
    max_long_edge: int,
    max_pixels: int,
) -> tuple[fitz.Pixmap, float]:
    for _ in range(4):
        pixmap = page.get_pixmap(
            matrix=fitz.Matrix(scale, scale),
            alpha=False,
        )
        pixel_count = pixmap.width * pixmap.height
        if max(pixmap.width, pixmap.height) <= max_long_edge and pixel_count <= max_pixels:
            return pixmap, scale
        correction = min(
            max_long_edge / max(pixmap.width, pixmap.height),
            math.sqrt(max_pixels / pixel_count),
        )
        scale *= correction * 0.999
    raise ValueError("unable to render page within VLM pixel limits")


def _pixel_to_canonical(
    bbox: PixelBoundingBox,
    rendered: _RenderedPage,
) -> CanonicalBoundingBox:
    if bbox.x1 > rendered.image_width or bbox.y1 > rendered.image_height:
        raise ValueError("VLM pixel bbox lies outside rendered page")
    return CanonicalBoundingBox(
        x0=bbox.x0 * rendered.transformer.page_width / rendered.image_width,
        y0=bbox.y0 * rendered.transformer.page_height / rendered.image_height,
        x1=bbox.x1 * rendered.transformer.page_width / rendered.image_width,
        y1=bbox.y1 * rendered.transformer.page_height / rendered.image_height,
    )


def _validate_internal_endpoint(endpoint: str, allowed_hosts: tuple[str, ...]) -> str:
    parsed = urlparse(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("document VLM endpoint must be an HTTP(S) URL")
    host = parsed.hostname.casefold()
    explicitly_allowed = {value.casefold() for value in allowed_hosts}
    local = host in {"localhost", "127.0.0.1", "::1"}
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None:
        local = address.is_private or address.is_loopback
    if not local and host not in explicitly_allowed:
        raise ValueError("document VLM endpoint must be local or explicitly allowed")
    return endpoint


def _result_model(
    models: set[tuple[str, str]],
    adapter: PaddleOCRVLAdapter,
) -> tuple[str, str]:
    if len(models) == 1:
        return next(iter(models))
    if len(models) > 1:
        return "mixed-document-vlm", "mixed"
    return adapter.model_name, adapter.model_version


def _elapsed_ms(started: float) -> float:
    return max(0.0, (time.perf_counter() - started) * 1000)
