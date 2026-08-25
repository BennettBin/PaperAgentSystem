"""Deterministic result fusion and quality gate for hybrid document parsing V2."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from statistics import fmean

from backend.document_processing.config import DocumentProcessingConfig
from backend.document_processing.schema_v2 import (
    AdapterParseResult,
    CanonicalDocumentV2,
    CanonicalPage,
    CanonicalSection,
    DocumentElement,
    DocumentQuality,
    DocumentRoutePlan,
    ElementType,
    Equation,
    Figure,
    NormalizedBoundingBox,
    PageQuality,
    ParseRoute,
    PipelineDescriptor,
    QualityStatus,
    ReconciliationDecision,
    SourceCandidate,
    StructuredTable,
    TableCell,
    normalize_element_text,
    stable_document_id,
    stable_element_id,
    stable_identifier,
)

_TEXT_TYPES = {
    ElementType.TITLE,
    ElementType.SECTION_HEADING,
    ElementType.PARAGRAPH,
    ElementType.LIST_ITEM,
    ElementType.CAPTION,
    ElementType.PAGE_HEADER,
    ElementType.PAGE_FOOTER,
    ElementType.FOOTNOTE,
    ElementType.CODE,
    ElementType.ALGORITHM,
    ElementType.REFERENCE,
    ElementType.UNKNOWN,
}
_STRUCTURAL_TYPES = {ElementType.TABLE, ElementType.FIGURE, ElementType.EQUATION}
_IGNORED_TYPES = {ElementType.TEXT_LINE, ElementType.TEXT_SPAN, ElementType.TABLE_CELL}


@dataclass
class _Candidate:
    element: DocumentElement
    parser_kind: str
    child_elements: tuple[DocumentElement, ...] = ()


@dataclass
class _Choice:
    accepted: _Candidate
    alternatives: list[_Candidate]
    reason: str
    absorbed: list[_Candidate] = field(default_factory=list)


class QualityGate:
    """Assign page/document states and define the only index-ready states."""

    def __init__(self, config: DocumentProcessingConfig | None = None) -> None:
        self.config = config or DocumentProcessingConfig()

    @staticmethod
    def is_ready(quality: DocumentQuality) -> bool:
        return quality.ready_for_index

    def page_quality(
        self,
        source: PageQuality,
        route: ParseRoute,
        *,
        warnings: tuple[str, ...],
        element_count: int,
    ) -> PageQuality:
        merged_warnings = tuple(dict.fromkeys((*source.warnings, *warnings)))
        score = source.overall if element_count else 0.0
        if not element_count:
            status = QualityStatus.FAILED
            merged_warnings = tuple(dict.fromkeys((*merged_warnings, "no_final_elements")))
        elif score >= self.config.quality_pass_threshold:
            status = QualityStatus.PASS_WITH_WARNINGS if merged_warnings else QualityStatus.PASS
        elif score >= self.config.quality_warning_threshold:
            status = QualityStatus.PASS_WITH_WARNINGS
            merged_warnings = tuple(dict.fromkeys((*merged_warnings, "quality_below_pass_threshold")))
        elif route is ParseRoute.DOCUMENT_VLM:
            status = QualityStatus.FAILED
            merged_warnings = tuple(dict.fromkeys((*merged_warnings, "vlm_quality_below_threshold")))
        else:
            status = QualityStatus.RETRY_WITH_VLM
            merged_warnings = tuple(dict.fromkeys((*merged_warnings, "quality_requires_vlm_retry")))
        return source.model_copy(
            update={"status": status, "overall": score, "warnings": merged_warnings}
        )

    def document_quality(self, pages: tuple[CanonicalPage, ...]) -> DocumentQuality:
        statuses = {page.quality.status for page in pages}
        if QualityStatus.FAILED in statuses:
            status = QualityStatus.FAILED
        elif QualityStatus.RETRY_WITH_VLM in statuses:
            status = QualityStatus.RETRY_WITH_VLM
        elif QualityStatus.PASS_WITH_WARNINGS in statuses:
            status = QualityStatus.PASS_WITH_WARNINGS
        else:
            status = QualityStatus.PASS
        warnings = tuple(
            dict.fromkeys(
                warning
                for page in pages
                for warning in page.quality.warnings
            )
        )
        return DocumentQuality(
            status=status,
            overall=fmean(page.quality.overall for page in pages) if pages else 0,
            warnings=warnings,
            failed_pages=tuple(
                page.page_number
                for page in pages
                if page.quality.status is QualityStatus.FAILED
            ),
        )


class ResultReconciler:
    """Fuse parser candidates spatially and rebuild a final traceable document graph."""

    def __init__(self, config: DocumentProcessingConfig | None = None) -> None:
        self.config = config or DocumentProcessingConfig()
        self.quality_gate = QualityGate(self.config)

    def reconcile(
        self,
        *,
        filename: str,
        checksum: str,
        pipeline: PipelineDescriptor,
        route_plan: DocumentRoutePlan,
        native: AdapterParseResult,
        layout: AdapterParseResult | None = None,
        vlm: AdapterParseResult | None = None,
    ) -> CanonicalDocumentV2:
        adapters = tuple(item for item in (native, layout, vlm) if item is not None)
        page_sources = {
            page.page_number: page
            for adapter in adapters
            for page in adapter.pages
        }
        native_pages = {page.page_number: page for page in native.pages}
        pages: list[CanonicalPage] = []
        decisions: list[ReconciliationDecision] = []
        for route_decision in route_plan.decisions:
            page_number = route_decision.page_number
            geometry_page = native_pages.get(page_number) or page_sources[page_number]
            candidates = self._page_candidates(adapters, page_number)
            choices = self._choose(candidates, route_decision.route)
            self._suppress_text_inside_structures(choices, route_decision.route)
            choices = self._add_selected_table_cells(choices)
            finalized, page_decisions = self._finalize_page(
                checksum, page_number, choices
            )
            warnings = self._page_warnings(adapters, page_number)
            source_quality = self._quality_source(
                adapters, page_number, route_decision.route
            ).quality
            quality = self.quality_gate.page_quality(
                source_quality,
                route_decision.route,
                warnings=warnings,
                element_count=len(finalized),
            )
            profile = geometry_page.profile.model_copy(
                update={
                    "proposed_route": route_decision.route,
                    "route_reasons": route_decision.reasons,
                }
            )
            pages.append(
                geometry_page.model_copy(
                    update={
                        "selected_route": route_decision.route,
                        "route_reasons": route_decision.reasons,
                        "profile": profile,
                        "elements": finalized,
                        "quality": quality,
                    }
                )
            )
            decisions.extend(page_decisions)

        rebuilt_pages, rebuilt_decisions = self._reclassify_repeated_margins(
            checksum, tuple(pages), tuple(decisions)
        )
        sections = self._build_sections(rebuilt_pages)
        tables = self._build_tables(rebuilt_pages)
        equations = self._build_equations(rebuilt_pages)
        figures = self._build_figures(rebuilt_pages)
        document_quality = self.quality_gate.document_quality(rebuilt_pages)
        return CanonicalDocumentV2(
            document_id=stable_document_id(checksum),
            filename=filename,
            checksum=checksum,
            page_count=len(rebuilt_pages),
            pipeline=pipeline,
            pipeline_fingerprint=pipeline.fingerprint,
            pages=rebuilt_pages,
            sections=sections,
            tables=tables,
            equations=equations,
            figures=figures,
            reconciliation_decisions=rebuilt_decisions,
            quality=document_quality,
        )

    def _page_candidates(
        self, adapters: tuple[AdapterParseResult, ...], page_number: int
    ) -> list[_Candidate]:
        result: list[_Candidate] = []
        for adapter in adapters:
            page = next((item for item in adapter.pages if item.page_number == page_number), None)
            if page is None:
                continue
            by_id = {element.element_id: element for element in page.elements}
            for element in page.elements:
                if element.element_type in _IGNORED_TYPES:
                    continue
                children = tuple(
                    by_id[child_id]
                    for child_id in element.children_ids
                    if child_id in by_id and by_id[child_id].element_type is ElementType.TABLE_CELL
                )
                result.append(
                    _Candidate(element, self._parser_kind(element.provenance.parser_name), children)
                )
        return result

    @staticmethod
    def _parser_kind(parser_name: str) -> str:
        lowered = parser_name.casefold()
        if "docling" in lowered or "layout" in lowered:
            return "layout"
        if "paddle" in lowered or "ocr" in lowered or "vlm" in lowered:
            return "vlm"
        return "native"

    def _choose(self, candidates: list[_Candidate], route: ParseRoute) -> list[_Choice]:
        clusters: list[list[_Candidate]] = []
        for candidate in candidates:
            for cluster in clusters:
                if self._aligned(candidate.element, cluster[0].element):
                    cluster.append(candidate)
                    break
            else:
                clusters.append([candidate])
        choices: list[_Choice] = []
        for cluster in clusters:
            accepted = max(cluster, key=lambda item: self._candidate_score(item, route))
            if accepted.element.element_type is ElementType.TABLE:
                reason = f"table structure completeness selected {len(accepted.child_elements)} cells"
            elif accepted.parser_kind == "native":
                reason = "native text preferred for clean body content"
            elif accepted.parser_kind == "layout":
                reason = "layout parser preferred for reading order and structure"
            else:
                reason = "VLM/OCR preferred for scanned or visually complex content"
            choices.append(_Choice(accepted, list(cluster), reason))
        return choices

    def _aligned(self, left: DocumentElement, right: DocumentElement) -> bool:
        if left.element_type is not right.element_type:
            return False
        overlap = self._iou(left.normalized_bbox, right.normalized_bbox)
        if overlap < self.config.fusion_bbox_iou_threshold:
            return False
        if left.element_type in _STRUCTURAL_TYPES:
            return True
        if left.element_type in _TEXT_TYPES:
            similarity = SequenceMatcher(
                None,
                normalize_element_text(left.text).casefold(),
                normalize_element_text(right.text).casefold(),
            ).ratio()
            return similarity >= self.config.fusion_text_similarity_threshold or overlap >= 0.85
        return False

    @staticmethod
    def _iou(left: NormalizedBoundingBox, right: NormalizedBoundingBox) -> float:
        x0, y0 = max(left.x0, right.x0), max(left.y0, right.y0)
        x1, y1 = min(left.x1, right.x1), min(left.y1, right.y1)
        intersection = max(0.0, x1 - x0) * max(0.0, y1 - y0)
        left_area = (left.x1 - left.x0) * (left.y1 - left.y0)
        right_area = (right.x1 - right.x0) * (right.y1 - right.y0)
        union = left_area + right_area - intersection
        return intersection / union if union else 0.0

    @staticmethod
    def _coverage(inner: NormalizedBoundingBox, outer: NormalizedBoundingBox) -> float:
        x0, y0 = max(inner.x0, outer.x0), max(inner.y0, outer.y0)
        x1, y1 = min(inner.x1, outer.x1), min(inner.y1, outer.y1)
        intersection = max(0.0, x1 - x0) * max(0.0, y1 - y0)
        area = (inner.x1 - inner.x0) * (inner.y1 - inner.y0)
        return intersection / area if area else 0.0

    @staticmethod
    def _candidate_score(candidate: _Candidate, route: ParseRoute) -> tuple[float, float, str]:
        if candidate.element.element_type is ElementType.TABLE:
            return (100 + len(candidate.child_elements), candidate.element.provenance.confidence, candidate.parser_kind)
        priority = {
            ParseRoute.FAST_NATIVE: {"native": 30, "layout": 20, "vlm": 10},
            ParseRoute.LAYOUT_NATIVE: {"layout": 30, "vlm": 20, "native": 10},
            ParseRoute.DOCUMENT_VLM: {"vlm": 30, "layout": 20, "native": 10},
            ParseRoute.FAILED: {"native": 0, "layout": 0, "vlm": 0},
        }[route][candidate.parser_kind]
        return (priority, candidate.element.provenance.confidence, candidate.parser_kind)

    def _suppress_text_inside_structures(
        self, choices: list[_Choice], route: ParseRoute
    ) -> None:
        structures = [
            item
            for item in choices
            if item.accepted.element.element_type in _STRUCTURAL_TYPES
            and not (
                route is ParseRoute.DOCUMENT_VLM
                and item.accepted.parser_kind == "native"
                and item.accepted.element.element_type is ElementType.FIGURE
            )
        ]
        for choice in tuple(choices):
            if choice.accepted.element.element_type not in _TEXT_TYPES:
                continue
            owner = next(
                (
                    structure
                    for structure in structures
                    if self._coverage(
                        choice.accepted.element.normalized_bbox,
                        structure.accepted.element.normalized_bbox,
                    )
                    >= 0.80
                ),
                None,
            )
            if owner is not None:
                owner.absorbed.extend(choice.alternatives)
                choices.remove(choice)

    @staticmethod
    def _add_selected_table_cells(choices: list[_Choice]) -> list[_Choice]:
        result = list(choices)
        for choice in choices:
            if choice.accepted.element.element_type is not ElementType.TABLE:
                continue
            for child in choice.accepted.child_elements:
                candidate = _Candidate(child, choice.accepted.parser_kind)
                result.append(_Choice(candidate, [candidate], "cell retained from selected table structure"))
        return result

    def _finalize_page(
        self, checksum: str, page_number: int, choices: list[_Choice]
    ) -> tuple[tuple[DocumentElement, ...], tuple[ReconciliationDecision, ...]]:
        ordered = sorted(
            choices,
            key=lambda item: (
                item.accepted.element.reading_order,
                item.accepted.element.bbox.y0,
                item.accepted.element.bbox.x0,
                item.accepted.element.element_type.value,
            ),
        )
        old_to_new: dict[str, str] = {}
        staged: list[tuple[_Choice, DocumentElement, tuple[SourceCandidate, ...], str]] = []
        for order, choice in enumerate(ordered):
            source = choice.accepted.element
            new_id = stable_element_id(
                checksum, page_number, source.element_type, order, source.bbox, source.text
            )
            old_to_new[source.element_id] = new_id
            candidate_values = tuple(
                self._source_candidate(candidate, candidate is choice.accepted, choice.reason)
                for candidate in (*choice.alternatives, *choice.absorbed)
            )
            staged.append((choice, source, candidate_values, new_id))
        elements: list[DocumentElement] = []
        decisions: list[ReconciliationDecision] = []
        child_map: dict[str, list[str]] = defaultdict(list)
        for choice, source, candidates, new_id in staged:
            parent_id = old_to_new.get(source.parent_id or "")
            if parent_id:
                child_map[parent_id].append(new_id)
            accepted_id = next(item.candidate_id for item in candidates if item.accepted)
            elements.append(
                source.model_copy(
                    update={
                        "element_id": new_id,
                        "reading_order": len(elements),
                        "parent_id": parent_id,
                        "children_ids": (),
                        "source_candidates": candidates,
                    }
                )
            )
            decisions.append(
                ReconciliationDecision(
                    decision_id=stable_identifier("decision", checksum, page_number, new_id),
                    page_number=page_number,
                    output_element_id=new_id,
                    accepted_candidate_id=accepted_id,
                    rejected_candidate_ids=tuple(
                        item.candidate_id for item in candidates if not item.accepted
                    ),
                    reason=choice.reason,
                    confidence=source.provenance.confidence,
                )
            )
        elements = [
            item.model_copy(update={"children_ids": tuple(child_map.get(item.element_id, ()))})
            for item in elements
        ]
        return tuple(elements), tuple(decisions)

    def _source_candidate(
        self, candidate: _Candidate, accepted: bool, reason: str
    ) -> SourceCandidate:
        element = candidate.element
        summary = element.text[: self.config.fusion_candidate_summary_characters]
        return SourceCandidate(
            candidate_id=stable_identifier(
                "cand", element.provenance.parser_name, element.element_id
            ),
            element_type=element.element_type,
            text=summary,
            bbox=element.bbox,
            normalized_bbox=element.normalized_bbox,
            reading_order=element.reading_order,
            provenance=element.provenance,
            accepted=accepted,
            decision_reason=reason if accepted else f"rejected: {reason}",
        )

    @staticmethod
    def _quality_source(
        adapters: tuple[AdapterParseResult, ...], page_number: int, route: ParseRoute
    ) -> CanonicalPage:
        target = {
            ParseRoute.FAST_NATIVE: "native",
            ParseRoute.LAYOUT_NATIVE: "layout",
            ParseRoute.DOCUMENT_VLM: "vlm",
            ParseRoute.FAILED: "native",
        }[route]
        pages = [
            page
            for adapter in adapters
            for page in adapter.pages
            if page.page_number == page_number
        ]
        for page in pages:
            parsers = {ResultReconciler._parser_kind(item.provenance.parser_name) for item in page.elements}
            if target in parsers:
                return page
        return pages[0]

    @staticmethod
    def _page_warnings(
        adapters: tuple[AdapterParseResult, ...], page_number: int
    ) -> tuple[str, ...]:
        warnings: list[str] = []
        marker = f"page_{page_number}:"
        for adapter in adapters:
            page = next((item for item in adapter.pages if item.page_number == page_number), None)
            if page:
                warnings.extend(page.quality.warnings)
            if page_number in adapter.failed_pages:
                warnings.append(f"{adapter.parser_name}_failed")
            for warning in adapter.warnings:
                if warning.startswith(marker):
                    warnings.append(warning[len(marker) :])
        return tuple(dict.fromkeys(warnings))

    def _reclassify_repeated_margins(
        self,
        checksum: str,
        pages: tuple[CanonicalPage, ...],
        decisions: tuple[ReconciliationDecision, ...],
    ) -> tuple[tuple[CanonicalPage, ...], tuple[ReconciliationDecision, ...]]:
        counts = Counter(
            normalize_element_text(element.text).casefold()
            for page in pages
            for element in page.elements
            if element.element_type in _TEXT_TYPES
            and (element.normalized_bbox.y1 <= 0.08 or element.normalized_bbox.y0 >= 0.92)
            and element.text.strip()
        )
        repeated = {text for text, count in counts.items() if count >= 2}
        if not repeated:
            return pages, decisions
        replacements: dict[str, str] = {}
        new_pages: list[CanonicalPage] = []
        for page in pages:
            new_elements: list[DocumentElement] = []
            for element in page.elements:
                normalized = normalize_element_text(element.text).casefold()
                new_type = element.element_type
                if normalized in repeated and element.normalized_bbox.y1 <= 0.08:
                    new_type = ElementType.PAGE_HEADER
                elif normalized in repeated and element.normalized_bbox.y0 >= 0.92:
                    new_type = ElementType.PAGE_FOOTER
                if new_type is element.element_type:
                    new_elements.append(element)
                    continue
                new_id = stable_element_id(
                    checksum,
                    page.page_number,
                    new_type,
                    element.reading_order,
                    element.bbox,
                    element.text,
                )
                replacements[element.element_id] = new_id
                candidates = tuple(
                    candidate.model_copy(update={"element_type": new_type})
                    for candidate in element.source_candidates
                )
                new_elements.append(
                    element.model_copy(
                        update={
                            "element_id": new_id,
                            "element_type": new_type,
                            "source_candidates": candidates,
                        }
                    )
                )
            new_pages.append(page.model_copy(update={"elements": tuple(new_elements)}))
        if not replacements:
            return pages, decisions
        new_decisions = tuple(
            decision.model_copy(
                update={
                    "decision_id": stable_identifier(
                        "decision",
                        checksum,
                        decision.page_number,
                        replacements.get(decision.output_element_id, decision.output_element_id),
                    ),
                    "output_element_id": replacements.get(
                        decision.output_element_id, decision.output_element_id
                    ),
                }
            )
            for decision in decisions
        )
        return tuple(new_pages), new_decisions

    @staticmethod
    def _heading_parts(text: str) -> tuple[str | None, int]:
        match = re.match(r"^\s*((?:\d+\.)*\d+)\s+", text)
        if not match:
            return None, 1
        number = match.group(1)
        return number, number.count(".") + 1

    def _build_sections(self, pages: tuple[CanonicalPage, ...]) -> tuple[CanonicalSection, ...]:
        flat = [element for page in pages for element in page.elements]
        headings = [(index, item) for index, item in enumerate(flat) if item.element_type is ElementType.SECTION_HEADING]
        result: list[CanonicalSection] = []
        stack: list[CanonicalSection] = []
        for ordinal, (start, heading) in enumerate(headings):
            number, level = self._heading_parts(heading.text)
            while stack and stack[-1].level >= level:
                stack.pop()
            end = headings[ordinal + 1][0] if ordinal + 1 < len(headings) else len(flat)
            members = tuple(item.element_id for item in flat[start:end])
            section_id = stable_identifier("sec", heading.element_id)
            parent = stack[-1] if stack else None
            section = CanonicalSection(
                section_id=section_id,
                title=heading.text,
                number=number,
                level=level,
                parent_section_id=parent.section_id if parent else None,
                section_path=(*(parent.section_path if parent else ()), heading.text),
                page_start=heading.page_number,
                page_end=flat[end - 1].page_number,
                heading_element_id=heading.element_id,
                element_ids=members,
                ordinal=ordinal,
            )
            result.append(section)
            stack.append(section)
        return tuple(result)

    @staticmethod
    def _nearest_caption(page: CanonicalPage, element: DocumentElement, prefix: str) -> DocumentElement | None:
        captions = [
            item
            for item in page.elements
            if item.element_type is ElementType.CAPTION
            and item.text.casefold().startswith(prefix.casefold())
        ]
        return min(captions, key=lambda item: abs(item.bbox.y0 - element.bbox.y0), default=None)

    def _build_tables(self, pages: tuple[CanonicalPage, ...]) -> tuple[StructuredTable, ...]:
        result: list[StructuredTable] = []
        for page in pages:
            by_id = {item.element_id: item for item in page.elements}
            for table in (item for item in page.elements if item.element_type is ElementType.TABLE):
                cells = []
                for child_id in table.children_ids:
                    child = by_id[child_id]
                    cells.append(TableCell(
                        cell_id=stable_identifier("cell", child.element_id),
                        page_number=page.page_number,
                        row_index=self._metadata_int(child, "row_index", 0),
                        column_index=self._metadata_int(child, "column_index", 0),
                        row_span=self._metadata_int(child, "row_span", 1),
                        column_span=self._metadata_int(child, "column_span", 1),
                        text=child.text,
                        bbox=child.bbox,
                        normalized_bbox=child.normalized_bbox,
                        confidence=child.provenance.confidence,
                    ))
                caption = self._nearest_caption(page, table, "table")
                result.append(StructuredTable(
                    table_id=stable_identifier("table", table.element_id),
                    page_number=page.page_number,
                    caption=caption.text if caption else "",
                    bbox=table.bbox,
                    normalized_bbox=table.normalized_bbox,
                    cells=tuple(cells),
                    source_element_ids=(
                        table.element_id,
                        *table.children_ids,
                        *((caption.element_id,) if caption else ()),
                    ),
                    markdown=table.text,
                ))
        return tuple(result)

    @staticmethod
    def _metadata_int(element: DocumentElement, key: str, default: int) -> int:
        value = element.metadata.get(key, default)
        return int(value) if isinstance(value, (str, int, float)) else default

    def _build_equations(self, pages: tuple[CanonicalPage, ...]) -> tuple[Equation, ...]:
        return tuple(
            Equation(
                equation_id=stable_identifier("eq", item.element_id),
                page_number=item.page_number,
                latex=str(item.metadata.get("latex") or item.text),
                bbox=item.bbox,
                normalized_bbox=item.normalized_bbox,
                confidence=item.provenance.confidence,
                source_element_ids=(item.element_id,),
            )
            for page in pages
            for item in page.elements
            if item.element_type is ElementType.EQUATION
        )

    def _build_figures(self, pages: tuple[CanonicalPage, ...]) -> tuple[Figure, ...]:
        result: list[Figure] = []
        for page in pages:
            for item in (element for element in page.elements if element.element_type is ElementType.FIGURE):
                caption = self._nearest_caption(page, item, "figure")
                source_ids = (item.element_id, *((caption.element_id,) if caption else ()))
                result.append(Figure(
                    figure_id=stable_identifier("fig", item.element_id),
                    page_number=item.page_number,
                    caption=caption.text if caption else "",
                    description=item.text,
                    description_is_inferred=item.metadata.get("content_kind") == "generated_description",
                    bbox=item.bbox,
                    normalized_bbox=item.normalized_bbox,
                    source_element_ids=source_ids,
                ))
        return tuple(result)
