"""Deterministic, explainable page routing for hybrid document parsing."""

from __future__ import annotations

from backend.document_processing.config import DocumentProcessingConfig
from backend.document_processing.schema_v2 import (
    DocumentRoutePlan,
    PageProfile,
    PageSignals,
    ParseRoute,
    RouteDecision,
)


class DeterministicParseRouter:
    def __init__(self, config: DocumentProcessingConfig | None = None) -> None:
        self._config = config or DocumentProcessingConfig()

    def profile(self, signals: PageSignals) -> PageProfile:
        decision = self.route_page(signals)
        return PageProfile(
            page_number=signals.page_number,
            native_character_count=signals.native_character_count,
            garble_ratio=signals.garble_ratio,
            image_coverage=signals.image_coverage,
            text_overlap_ratio=signals.text_overlap_ratio,
            bbox_out_of_bounds_ratio=signals.bbox_out_of_bounds_ratio,
            detected_column_count=signals.detected_column_count,
            has_tables=signals.has_tables,
            has_formulas=signals.has_formulas,
            has_drawings=signals.has_drawings,
            rotation=signals.rotation,
            proposed_route=decision.route,
            route_reasons=decision.reasons,
        )

    def route_document(self, pages: tuple[PageSignals, ...]) -> DocumentRoutePlan:
        decisions = tuple(self.route_page(page) for page in pages)
        vlm_pages = tuple(
            decision.page_number
            for decision in decisions
            if decision.route is ParseRoute.DOCUMENT_VLM
        )
        limit = self._config.vlm_max_pages_per_document
        document_route = _aggregate_route(decisions)
        return DocumentRoutePlan(
            document_route=document_route,
            decisions=decisions,
            vlm_page_count=len(vlm_pages),
            vlm_page_limit=limit,
            budget_exceeded=len(vlm_pages) > limit,
            blocked_page_numbers=vlm_pages[limit:],
        )

    def route_page(self, signals: PageSignals) -> RouteDecision:
        vlm_reasons = self._vlm_reasons(signals)
        if vlm_reasons:
            return RouteDecision(
                page_number=signals.page_number,
                route=ParseRoute.DOCUMENT_VLM,
                reasons=tuple(vlm_reasons),
                fallback_routes=(ParseRoute.LAYOUT_NATIVE, ParseRoute.FAST_NATIVE),
            )
        layout_reasons = self._layout_reasons(signals)
        if layout_reasons:
            return RouteDecision(
                page_number=signals.page_number,
                route=ParseRoute.LAYOUT_NATIVE,
                reasons=tuple(layout_reasons),
                fallback_routes=(ParseRoute.FAST_NATIVE, ParseRoute.DOCUMENT_VLM),
            )
        return RouteDecision(
            page_number=signals.page_number,
            route=ParseRoute.FAST_NATIVE,
            reasons=("native_text_quality_sufficient",),
            fallback_routes=(ParseRoute.LAYOUT_NATIVE, ParseRoute.DOCUMENT_VLM),
        )

    def _vlm_reasons(self, signals: PageSignals) -> list[str]:
        reasons: list[str] = []
        insufficient_text = (
            signals.native_character_count < self._config.native_min_characters_per_page
        )
        if signals.garble_ratio > self._config.native_max_garble_ratio:
            reasons.append("native_text_garbled")
        if signals.native_character_count == 0 and signals.image_block_count > 0:
            reasons.append("no_native_text_image_page")
        elif insufficient_text and (
            signals.image_coverage >= self._config.image_coverage_vlm_threshold
        ):
            reasons.append("insufficient_native_text_image_dominant")
        return reasons

    def _layout_reasons(self, signals: PageSignals) -> list[str]:
        reasons: list[str] = []
        if signals.detected_column_count >= 2:
            reasons.append("multi_column_layout")
        if signals.has_tables:
            reasons.append("table_structure_detected")
        if signals.has_formulas:
            reasons.append("formula_structure_detected")
        if signals.text_overlap_ratio > self._config.text_overlap_layout_threshold:
            reasons.append("text_overlap_high")
        if (
            signals.bbox_out_of_bounds_ratio
            > self._config.bbox_out_of_bounds_layout_threshold
        ):
            reasons.append("native_bbox_out_of_bounds")
        if signals.suspected_duplicate_ocr:
            reasons.append("duplicate_text_layer_suspected")
        if signals.rotation != 0:
            reasons.append("rotated_page")
        if signals.cropbox_differs_from_mediabox:
            reasons.append("cropbox_differs_from_mediabox")
        if signals.drawing_count >= self._config.drawing_count_layout_threshold:
            reasons.append("drawing_heavy_layout")
        return reasons


def _aggregate_route(decisions: tuple[RouteDecision, ...]) -> ParseRoute:
    routes = {decision.route for decision in decisions}
    if ParseRoute.FAILED in routes:
        return ParseRoute.FAILED
    if ParseRoute.DOCUMENT_VLM in routes:
        return ParseRoute.DOCUMENT_VLM
    if ParseRoute.LAYOUT_NATIVE in routes:
        return ParseRoute.LAYOUT_NATIVE
    return ParseRoute.FAST_NATIVE
