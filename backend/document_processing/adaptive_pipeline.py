"""Production composition for the Canonical Document V2 parser."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable

from pydantic import BaseModel, ConfigDict, Field

from backend.core.errors import ErrorCode, ProjectError
from backend.core.ports.document_processing import (
    DocumentLayoutAdapter,
    DocumentVLMAdapter,
    PageParserAdapter,
)
from backend.document_processing.config import DocumentProcessingConfig
from backend.document_processing.office_adapter import DoclingOfficeAdapter
from backend.document_processing.preflight import PDFPreflight
from backend.document_processing.profiler import PageProfiler
from backend.document_processing.reconciler import ResultReconciler
from backend.document_processing.router import DeterministicParseRouter
from backend.document_processing.schema_v2 import (
    AdapterParseResult,
    CanonicalDocumentV2,
    DocumentRoutePlan,
    PageSelection,
    ParseRoute,
    ParsingContext,
    PipelineComponent,
    PipelineDescriptor,
)

ProgressCallback = Callable[[str], None]


class PageParseDiagnostic(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    page_number: int = Field(ge=1)
    route: ParseRoute
    reasons: tuple[str, ...] = ()
    quality_status: str
    quality_score: float = Field(ge=0, le=1)
    warnings: tuple[str, ...] = ()
    selected_sources: tuple[str, ...] = ()


class AdaptiveParseDiagnostics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    pipeline_fingerprint: str
    document_route: ParseRoute
    pages: tuple[PageParseDiagnostic, ...]
    components: tuple[PipelineComponent, ...]
    stage_timings_ms: dict[str, float]
    vlm_page_count: int = Field(ge=0)
    vlm_rendered_pixels: int = Field(ge=0)
    vlm_service_calls: int = Field(ge=0)
    vlm_fallback_count: int = Field(ge=0)
    failed_adapter_pages: int = Field(ge=0)


class AdaptiveParseOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    document: CanonicalDocumentV2
    diagnostics: AdaptiveParseDiagnostics


class ProductionParseOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    document: CanonicalDocumentV2
    diagnostics: AdaptiveParseDiagnostics | None = None


class AdaptiveDocumentPipeline:
    """Route individual pages, run bounded adapters and reconcile one V2 document."""

    def __init__(
        self,
        native: PageParserAdapter,
        layout: DocumentLayoutAdapter,
        vlm: DocumentVLMAdapter,
        *,
        config: DocumentProcessingConfig | None = None,
        docling_enabled: bool = True,
        document_vlm_enabled: bool = True,
        preflight: PDFPreflight | None = None,
        profiler: PageProfiler | None = None,
        router: DeterministicParseRouter | None = None,
        reconciler: ResultReconciler | None = None,
    ) -> None:
        self._config = config or DocumentProcessingConfig()
        self._native = native
        self._layout = layout
        self._vlm = vlm
        self._docling_enabled = docling_enabled
        self._vlm_enabled = document_vlm_enabled
        self._preflight = preflight or PDFPreflight(self._config)
        self._profiler = profiler or PageProfiler()
        self._router = router or DeterministicParseRouter(self._config)
        self._reconciler = reconciler or ResultReconciler(self._config)
        self._descriptor = PipelineDescriptor(
            router_version=getattr(self._router, "version", "2.0.0"),
            render_scale=self._config.render_scale,
            components=tuple(
                self._component(adapter) for adapter in (native, layout, vlm)
            ),
            config={
                "docling_enabled": docling_enabled,
                "document_vlm_enabled": document_vlm_enabled,
                "vlm_max_pages_per_document": self._config.vlm_max_pages_per_document,
            },
        )

    @property
    def descriptor(self) -> PipelineDescriptor:
        return self._descriptor

    async def parse(
        self,
        file_data: bytes,
        filename: str,
        *,
        trace_id: str,
    ) -> CanonicalDocumentV2:
        return (await self.parse_with_diagnostics(file_data, filename, trace_id=trace_id)).document

    async def parse_with_diagnostics(
        self,
        file_data: bytes,
        filename: str,
        *,
        trace_id: str,
        progress: ProgressCallback | None = None,
    ) -> AdaptiveParseOutcome:
        timings: dict[str, float] = {}
        started = time.perf_counter()
        self._progress(progress, "profiling")
        preflight = self._preflight.inspect(file_data, filename)
        signals = self._profiler.profile_document(file_data)
        route_plan = self._router.route_document(signals)
        timings["profiling"] = self._elapsed(started)

        context = ParsingContext(
            trace_id=trace_id or "document-parse",
            document_checksum=preflight.checksum,
            pipeline=self._descriptor,
            timeout_seconds=self._config.parse_timeout_seconds,
        )
        all_pages = PageSelection(page_numbers=tuple(range(1, preflight.page_count + 1)))
        layout_pages = self._selection(route_plan, ParseRoute.LAYOUT_NATIVE)
        vlm_pages = self._selection(route_plan, ParseRoute.DOCUMENT_VLM)

        self._progress(progress, "parsing")
        parse_started = time.perf_counter()
        native_result = await self._native.parse_pages(file_data, filename, all_pages, context)
        layout_result = await self._optional_parse(
            self._layout,
            self._docling_enabled,
            "docling_disabled",
            file_data,
            filename,
            layout_pages,
            context,
        )
        vlm_result = await self._optional_parse(
            self._vlm,
            self._vlm_enabled,
            "document_vlm_disabled",
            file_data,
            filename,
            vlm_pages,
            context,
        )
        timings["parsing"] = self._elapsed(parse_started)

        self._progress(progress, "enriching")
        enrich_started = time.perf_counter()
        document = self._reconciler.reconcile(
            filename=filename,
            checksum=hashlib.sha256(file_data).hexdigest(),
            pipeline=self._descriptor,
            route_plan=route_plan,
            native=native_result,
            layout=layout_result,
            vlm=vlm_result,
        )
        timings["enriching"] = self._elapsed(enrich_started)
        timings["total"] = self._elapsed(started)
        diagnostics = self._diagnostics(
            document, route_plan, timings, layout_result, vlm_result
        )
        return AdaptiveParseOutcome(document=document, diagnostics=diagnostics)

    async def _optional_parse(
        self,
        adapter: PageParserAdapter,
        enabled: bool,
        disabled_warning: str,
        file_data: bytes,
        filename: str,
        selection: PageSelection | None,
        context: ParsingContext,
    ) -> AdapterParseResult | None:
        if selection is None:
            return None
        if enabled:
            return await adapter.parse_pages(file_data, filename, selection, context)
        return AdapterParseResult(
            parser_name=adapter.name,
            parser_version=adapter.version,
            selection=selection,
            pages=(),
            warnings=tuple(f"page_{page}:{disabled_warning}" for page in selection.page_numbers),
            failed_pages=selection.page_numbers,
        )

    def _diagnostics(
        self,
        document: CanonicalDocumentV2,
        route_plan: DocumentRoutePlan,
        timings: dict[str, float],
        layout: AdapterParseResult | None,
        vlm: AdapterParseResult | None,
    ) -> AdaptiveParseDiagnostics:
        page_rows = []
        for page in document.pages:
            sources = tuple(
                dict.fromkeys(element.provenance.parser_name for element in page.elements)
            )
            page_rows.append(
                PageParseDiagnostic(
                    page_number=page.page_number,
                    route=page.selected_route,
                    reasons=page.route_reasons,
                    quality_status=page.quality.status.value,
                    quality_score=page.quality.overall,
                    warnings=page.quality.warnings,
                    selected_sources=sources,
                )
            )
        metrics = vlm.metrics if vlm is not None else {}
        return AdaptiveParseDiagnostics(
            pipeline_fingerprint=document.pipeline_fingerprint,
            document_route=route_plan.document_route,
            pages=tuple(page_rows),
            components=self._descriptor.components,
            stage_timings_ms=timings,
            vlm_page_count=route_plan.vlm_page_count,
            vlm_rendered_pixels=int(metrics.get("rendered_pixel_count") or 0),
            vlm_service_calls=int(metrics.get("service_call_count") or 0),
            vlm_fallback_count=int(metrics.get("fallback_count") or 0),
            failed_adapter_pages=sum(
                len(item.failed_pages) for item in (layout, vlm) if item is not None
            ),
        )

    @staticmethod
    def _selection(plan: DocumentRoutePlan, route: ParseRoute) -> PageSelection | None:
        pages = tuple(item.page_number for item in plan.decisions if item.route is route)
        return PageSelection(page_numbers=pages) if pages else None

    @staticmethod
    def _component(adapter: PageParserAdapter) -> PipelineComponent:
        return PipelineComponent(
            name=adapter.name,
            version=adapter.version,
            model_name=getattr(adapter, "model_name", None),
            model_version=getattr(adapter, "model_version", None),
        )

    @staticmethod
    def _elapsed(started: float) -> float:
        return round((time.perf_counter() - started) * 1000, 3)

    @staticmethod
    def _progress(callback: ProgressCallback | None, status: str) -> None:
        if callback is not None:
            callback(status)


class ProductionDocumentPipeline:
    """Parse every supported document into Canonical Document V2."""

    def __init__(
        self,
        adaptive: AdaptiveDocumentPipeline,
        *,
        office: DoclingOfficeAdapter | None = None,
    ) -> None:
        self.adaptive = adaptive
        self.office = office

    async def parse(
        self,
        file_data: bytes,
        filename: str,
        *,
        trace_id: str,
        progress: ProgressCallback | None = None,
        workspace_id: str = "local-workspace",
    ) -> ProductionParseOutcome:
        del workspace_id
        checksum = hashlib.sha256(file_data).hexdigest()
        if filename.casefold().endswith((".docx", ".pptx")):
            if self.office is None:
                raise ProjectError(
                    ErrorCode.PARSING_FAILED,
                    "Office parsing is not configured",
                )
            self._progress(progress, "profiling")
            context = ParsingContext(
                trace_id=trace_id or "office-parse",
                document_checksum=checksum,
                pipeline=PipelineDescriptor(
                    router_version="office-bootstrap",
                    render_scale=1,
                    components=(),
                ),
                timeout_seconds=120,
            )
            self._progress(progress, "parsing")
            document = await self.office.parse(
                file_data, filename, context=context
            )
            self._progress(progress, "enriching")
            return ProductionParseOutcome(
                document=document,
            )
        outcome = await self.adaptive.parse_with_diagnostics(
            file_data, filename, trace_id=trace_id, progress=progress
        )
        return ProductionParseOutcome(
            document=outcome.document,
            diagnostics=outcome.diagnostics,
        )

    @staticmethod
    def _progress(callback: ProgressCallback | None, status: str) -> None:
        if callback is not None:
            callback(status)
