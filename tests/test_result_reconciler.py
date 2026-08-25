from __future__ import annotations

import hashlib

import pytest

from backend.document_processing.reconciler import QualityGate, ResultReconciler
from backend.document_processing.schema_v2 import (
    AdapterParseResult,
    CanonicalBoundingBox,
    CanonicalPage,
    CoordinateSpace,
    DocumentElement,
    DocumentRoutePlan,
    ElementType,
    NormalizedBoundingBox,
    PageProfile,
    PageQuality,
    PageSelection,
    ParseRoute,
    ParserProvenance,
    PipelineComponent,
    PipelineDescriptor,
    QualityStatus,
    RouteDecision,
    stable_element_id,
)

CHECKSUM = hashlib.sha256(b"result-reconciler-v06").hexdigest()
PAGE_BOX = CanonicalBoundingBox(x0=0, y0=0, x1=600, y1=800)


def pipeline() -> PipelineDescriptor:
    return PipelineDescriptor(
        router_version="router-v1",
        render_scale=2,
        components=(
            PipelineComponent(name="pymupdf-native-v2", version="2.0.0"),
            PipelineComponent(name="docling-layout-v2", version="2.0.0"),
            PipelineComponent(
                name="paddleocr-vl-v2",
                version="2.0.0",
                model_name="PaddleOCR-VL-1.6-0.9B",
                model_version="1.6",
            ),
            PipelineComponent(name="result-reconciler", version="2.0.0"),
        ),
    )


def bbox(x0: float, y0: float, x1: float, y1: float) -> CanonicalBoundingBox:
    return CanonicalBoundingBox(x0=x0, y0=y0, x1=x1, y1=y1)


def element(
    parser: str,
    element_type: ElementType,
    text: str,
    box: CanonicalBoundingBox,
    order: int,
    *,
    confidence: float = 0.95,
    inferred: bool = False,
    metadata: dict[str, str | int | float | bool | None] | None = None,
    parent_id: str | None = None,
    children_ids: tuple[str, ...] = (),
    page_number: int = 1,
) -> DocumentElement:
    identifier = stable_element_id(
        CHECKSUM,
        page_number,
        element_type,
        order,
        box,
        text,
    )
    return DocumentElement(
        element_id=identifier,
        page_number=page_number,
        element_type=element_type,
        text=text,
        normalized_text=text,
        bbox=box,
        normalized_bbox=NormalizedBoundingBox(
            x0=box.x0 / 600,
            y0=box.y0 / 800,
            x1=box.x1 / 600,
            y1=box.y1 / 800,
        ),
        reading_order=order,
        provenance=ParserProvenance(
            parser_name=parser,
            parser_version="2.0.0",
            model_name=("PaddleOCR-VL-1.6-0.9B" if "paddleocr" in parser else None),
            model_version=("1.6" if "paddleocr" in parser else None),
            confidence=confidence,
            source_coordinate_space=CoordinateSpace.PDF_POINT,
            is_inferred=inferred,
        ),
        parent_id=parent_id,
        children_ids=children_ids,
        is_inferred=inferred,
        metadata=metadata or {},
    )


def page(
    parser: str,
    route: ParseRoute,
    elements: tuple[DocumentElement, ...],
    *,
    score: float = 0.95,
    warnings: tuple[str, ...] = (),
    page_number: int = 1,
) -> CanonicalPage:
    return CanonicalPage(
        page_number=page_number,
        width=600,
        height=800,
        cropbox=PAGE_BOX,
        selected_route=route,
        route_reasons=("fixture_route",) if route is not ParseRoute.FAST_NATIVE else (),
        profile=PageProfile(
            page_number=page_number,
            native_character_count=sum(len(item.text) for item in elements),
            garble_ratio=0,
            image_coverage=0 if route is not ParseRoute.DOCUMENT_VLM else 1,
            text_overlap_ratio=0,
            bbox_out_of_bounds_ratio=0,
            detected_column_count=2 if route is ParseRoute.LAYOUT_NATIVE else 1,
            has_tables=any(item.element_type is ElementType.TABLE for item in elements),
            has_formulas=any(item.element_type is ElementType.EQUATION for item in elements),
            proposed_route=route,
            route_reasons=("fixture_route",) if route is not ParseRoute.FAST_NATIVE else (),
        ),
        elements=elements,
        quality=PageQuality(
            status=(QualityStatus.PASS if not warnings else QualityStatus.PASS_WITH_WARNINGS),
            overall=score,
            text=score,
            coordinates=score,
            reading_order=score,
            structure=score,
            ocr=score,
            tables=score,
            completeness=score,
            warnings=warnings,
        ),
    )


def adapter_result(
    parser: str,
    pages: tuple[CanonicalPage, ...],
    *,
    selected: tuple[int, ...] | None = None,
    failed: tuple[int, ...] = (),
    warnings: tuple[str, ...] = (),
) -> AdapterParseResult:
    selected_pages = selected or tuple(page.page_number for page in pages)
    return AdapterParseResult(
        parser_name=parser,
        parser_version="2.0.0",
        selection=PageSelection(page_numbers=selected_pages),
        pages=pages,
        failed_pages=failed,
        warnings=warnings,
    )


def route_plan(*routes: ParseRoute) -> DocumentRoutePlan:
    decisions = tuple(
        RouteDecision(
            page_number=index,
            route=route,
            reasons=("fixture_route",) if route is not ParseRoute.FAST_NATIVE else ("native_text_clean",),
        )
        for index, route in enumerate(routes, start=1)
    )
    vlm_count = sum(route is ParseRoute.DOCUMENT_VLM for route in routes)
    return DocumentRoutePlan(
        document_route=(
            ParseRoute.DOCUMENT_VLM
            if ParseRoute.DOCUMENT_VLM in routes
            else ParseRoute.LAYOUT_NATIVE
            if ParseRoute.LAYOUT_NATIVE in routes
            else ParseRoute.FAST_NATIVE
        ),
        decisions=decisions,
        vlm_page_count=vlm_count,
        vlm_page_limit=10,
    )


def reconcile(
    native: AdapterParseResult,
    plan: DocumentRoutePlan,
    *,
    layout: AdapterParseResult | None = None,
    vlm: AdapterParseResult | None = None,
):
    return ResultReconciler().reconcile(
        filename="paper.pdf",
        checksum=CHECKSUM,
        pipeline=pipeline(),
        route_plan=plan,
        native=native,
        layout=layout,
        vlm=vlm,
    )


def table_elements(
    parser: str,
    cell_count: int,
    *,
    order: int = 0,
) -> tuple[DocumentElement, ...]:
    table_box = bbox(50, 200, 550, 500)
    temporary_table = element(parser, ElementType.TABLE, "Model Score", table_box, order)
    cells: list[DocumentElement] = []
    cell_ids: list[str] = []
    for index in range(cell_count):
        row, column = divmod(index, 2)
        cell_box = bbox(50 + column * 250, 200 + row * 50, 300 + column * 250, 250 + row * 50)
        cell = element(
            parser,
            ElementType.TABLE_CELL,
            f"cell-{index}",
            cell_box,
            order + index + 1,
            metadata={
                "row_index": row,
                "column_index": column,
                "row_span": 1,
                "column_span": 1,
            },
            parent_id=temporary_table.element_id,
        )
        cells.append(cell)
        cell_ids.append(cell.element_id)
    table = temporary_table.model_copy(update={"children_ids": tuple(cell_ids)})
    return (table, *cells)


def test_fast_native_text_beats_overlapping_ocr_without_duplicate_output() -> None:
    box = bbox(40, 100, 560, 160)
    native_item = element("pymupdf-native-v2", ElementType.PARAGRAPH, "same evidence", box, 0)
    ocr_item = element("paddleocr-vl-v2", ElementType.PARAGRAPH, "same evidence", box, 0)
    document = reconcile(
        adapter_result("pymupdf-native-v2", (page("pymupdf-native-v2", ParseRoute.FAST_NATIVE, (native_item,)),)),
        route_plan(ParseRoute.FAST_NATIVE),
        vlm=adapter_result("paddleocr-vl-v2", (page("paddleocr-vl-v2", ParseRoute.DOCUMENT_VLM, (ocr_item,)),)),
    )

    paragraphs = [item for item in document.pages[0].elements if item.element_type is ElementType.PARAGRAPH]
    assert len(paragraphs) == 1
    assert paragraphs[0].provenance.parser_name == "pymupdf-native-v2"
    assert len(paragraphs[0].source_candidates) == 2
    assert sum(candidate.accepted for candidate in paragraphs[0].source_candidates) == 1
    assert "native" in next(
        decision.reason
        for decision in document.reconciliation_decisions
        if decision.output_element_id == paragraphs[0].element_id
    )


def test_same_text_in_different_regions_is_not_globally_deduplicated() -> None:
    items = (
        element("pymupdf-native-v2", ElementType.PARAGRAPH, "Repeated", bbox(40, 100, 200, 140), 0),
        element("pymupdf-native-v2", ElementType.PARAGRAPH, "Repeated", bbox(40, 500, 200, 540), 1),
    )
    document = reconcile(
        adapter_result("pymupdf-native-v2", (page("pymupdf-native-v2", ParseRoute.FAST_NATIVE, items),)),
        route_plan(ParseRoute.FAST_NATIVE),
    )

    assert [item.text for item in document.pages[0].elements] == ["Repeated", "Repeated"]


def test_layout_route_prefers_docling_reading_order_and_heading_role() -> None:
    first_box, second_box = bbox(40, 100, 280, 300), bbox(320, 100, 560, 300)
    native_items = (
        element("pymupdf-native-v2", ElementType.PARAGRAPH, "right column", second_box, 0),
        element("pymupdf-native-v2", ElementType.PARAGRAPH, "left column", first_box, 1),
    )
    layout_items = (
        element("docling-layout-v2", ElementType.PARAGRAPH, "left column", first_box, 0),
        element("docling-layout-v2", ElementType.PARAGRAPH, "right column", second_box, 1),
    )
    document = reconcile(
        adapter_result("pymupdf-native-v2", (page("pymupdf-native-v2", ParseRoute.LAYOUT_NATIVE, native_items),)),
        route_plan(ParseRoute.LAYOUT_NATIVE),
        layout=adapter_result("docling-layout-v2", (page("docling-layout-v2", ParseRoute.LAYOUT_NATIVE, layout_items),)),
    )

    assert [item.text for item in document.pages[0].elements] == ["left column", "right column"]
    assert all(item.provenance.parser_name == "docling-layout-v2" for item in document.pages[0].elements)


def test_document_vlm_route_prefers_ocr_candidate() -> None:
    box = bbox(40, 100, 560, 160)
    native_item = element("pymupdf-native-v2", ElementType.PARAGRAPH, "garbled text", box, 0, confidence=0.3)
    vlm_item = element("paddleocr-vl-v2", ElementType.PARAGRAPH, "clean scanned text", box, 0)
    document = reconcile(
        adapter_result("pymupdf-native-v2", (page("pymupdf-native-v2", ParseRoute.DOCUMENT_VLM, (native_item,), score=0.3),)),
        route_plan(ParseRoute.DOCUMENT_VLM),
        vlm=adapter_result("paddleocr-vl-v2", (page("paddleocr-vl-v2", ParseRoute.DOCUMENT_VLM, (vlm_item,)),)),
    )

    assert document.pages[0].elements[0].text == "clean scanned text"
    assert document.pages[0].elements[0].provenance.parser_name == "paddleocr-vl-v2"


def test_native_full_page_scan_figure_does_not_suppress_vlm_text() -> None:
    native_figure = element(
        "pymupdf-native-v2",
        ElementType.FIGURE,
        "",
        bbox(0, 0, 600, 800),
        0,
    )
    vlm_text = element(
        "paddleocr-vl-v2",
        ElementType.PARAGRAPH,
        "recognized scan evidence",
        bbox(40, 120, 560, 190),
        0,
    )
    document = reconcile(
        adapter_result(
            "pymupdf-native-v2",
            (
                page(
                    "pymupdf-native-v2",
                    ParseRoute.DOCUMENT_VLM,
                    (native_figure,),
                    score=0.2,
                ),
            ),
        ),
        route_plan(ParseRoute.DOCUMENT_VLM),
        vlm=adapter_result(
            "paddleocr-vl-v2",
            (
                page(
                    "paddleocr-vl-v2",
                    ParseRoute.DOCUMENT_VLM,
                    (vlm_text,),
                ),
            ),
        ),
    )

    assert any(item.text == "recognized scan evidence" for item in document.pages[0].elements)


def test_table_selection_uses_structure_completeness_not_fixed_parser_priority() -> None:
    native_table = table_elements("pymupdf-native-v2", 0)
    layout_table = table_elements("docling-layout-v2", 2)
    vlm_table = table_elements("paddleocr-vl-v2", 4)
    document = reconcile(
        adapter_result("pymupdf-native-v2", (page("pymupdf-native-v2", ParseRoute.LAYOUT_NATIVE, native_table),)),
        route_plan(ParseRoute.LAYOUT_NATIVE),
        layout=adapter_result("docling-layout-v2", (page("docling-layout-v2", ParseRoute.LAYOUT_NATIVE, layout_table),)),
        vlm=adapter_result("paddleocr-vl-v2", (page("paddleocr-vl-v2", ParseRoute.DOCUMENT_VLM, vlm_table),)),
    )

    table = next(item for item in document.pages[0].elements if item.element_type is ElementType.TABLE)
    cells = [item for item in document.pages[0].elements if item.element_type is ElementType.TABLE_CELL]
    assert table.provenance.parser_name == "paddleocr-vl-v2"
    assert len(cells) == 4
    assert len(document.tables) == 1
    assert len(document.tables[0].cells) == 4


def test_structured_table_absorbs_overlapping_native_text_layer() -> None:
    native_text = element(
        "pymupdf-native-v2",
        ElementType.PARAGRAPH,
        "A 1 B 2",
        bbox(80, 230, 520, 300),
        0,
    )
    layout_table = table_elements("docling-layout-v2", 4)
    document = reconcile(
        adapter_result("pymupdf-native-v2", (page("pymupdf-native-v2", ParseRoute.LAYOUT_NATIVE, (native_text,)),)),
        route_plan(ParseRoute.LAYOUT_NATIVE),
        layout=adapter_result("docling-layout-v2", (page("docling-layout-v2", ParseRoute.LAYOUT_NATIVE, layout_table),)),
    )

    assert all(item.element_type is not ElementType.PARAGRAPH for item in document.pages[0].elements)
    table = next(item for item in document.pages[0].elements if item.element_type is ElementType.TABLE)
    assert any(candidate.text == "A 1 B 2" and not candidate.accepted for candidate in table.source_candidates)


def test_sections_are_rebuilt_only_from_final_element_ids() -> None:
    elements = (
        element("docling-layout-v2", ElementType.SECTION_HEADING, "1 Methods", bbox(40, 80, 300, 120), 0),
        element("docling-layout-v2", ElementType.PARAGRAPH, "Method body", bbox(40, 130, 560, 200), 1),
        element("docling-layout-v2", ElementType.SECTION_HEADING, "1.1 Data", bbox(40, 220, 300, 260), 2),
        element("docling-layout-v2", ElementType.PARAGRAPH, "Data body", bbox(40, 270, 560, 340), 3),
    )
    document = reconcile(
        adapter_result("pymupdf-native-v2", (page("pymupdf-native-v2", ParseRoute.LAYOUT_NATIVE, elements),)),
        route_plan(ParseRoute.LAYOUT_NATIVE),
    )
    final_ids = {item.element_id for item in document.pages[0].elements}

    assert len(document.sections) == 2
    assert document.sections[1].parent_section_id == document.sections[0].section_id
    assert all(section.heading_element_id in final_ids for section in document.sections)
    assert all(set(section.element_ids) <= final_ids for section in document.sections)


def test_tables_equations_figures_and_captions_are_rebuilt_from_final_elements() -> None:
    table = table_elements("paddleocr-vl-v2", 2)
    extra = (
        element("paddleocr-vl-v2", ElementType.CAPTION, "Table 1 Results", bbox(50, 160, 400, 190), 3),
        element(
            "paddleocr-vl-v2",
            ElementType.EQUATION,
            "E = mc^2 (1)",
            bbox(100, 540, 400, 580),
            4,
            metadata={"latex": "E = mc^2", "content_kind": "ocr_text"},
        ),
        element(
            "paddleocr-vl-v2",
            ElementType.FIGURE,
            "A rising line chart",
            bbox(80, 600, 500, 740),
            5,
            inferred=True,
            metadata={"content_kind": "generated_description"},
        ),
        element("paddleocr-vl-v2", ElementType.CAPTION, "Figure 1 Trend", bbox(80, 750, 400, 780), 6),
    )
    document = reconcile(
        adapter_result("pymupdf-native-v2", (page("pymupdf-native-v2", ParseRoute.DOCUMENT_VLM, (*table, *extra)),)),
        route_plan(ParseRoute.DOCUMENT_VLM),
    )
    final_ids = {item.element_id for item in document.pages[0].elements}

    assert document.tables[0].caption == "Table 1 Results"
    assert document.equations[0].latex == "E = mc^2"
    assert document.figures[0].description == "A rising line chart"
    assert document.figures[0].description_is_inferred is True
    assert document.figures[0].caption == "Figure 1 Trend"
    assert all(set(item.source_element_ids) <= final_ids for item in (*document.tables, *document.equations, *document.figures))


def test_repeated_margin_text_is_rebuilt_as_header_without_misclassifying_unique_title() -> None:
    pages = []
    for page_number in (1, 2):
        items = (
            element("pymupdf-native-v2", ElementType.PARAGRAPH, "Repeated Journal 2026", bbox(40, 10, 300, 35), 0, page_number=page_number),
            element("pymupdf-native-v2", ElementType.TITLE, f"Unique title {page_number}", bbox(40, 45, 400, 90), 1, page_number=page_number),
        )
        pages.append(page("pymupdf-native-v2", ParseRoute.FAST_NATIVE, items, page_number=page_number))
    document = reconcile(
        adapter_result("pymupdf-native-v2", tuple(pages)),
        route_plan(ParseRoute.FAST_NATIVE, ParseRoute.FAST_NATIVE),
    )

    assert sum(
        item.element_type is ElementType.PAGE_HEADER
        for page_value in document.pages
        for item in page_value.elements
    ) == 2
    assert sum(
        item.element_type is ElementType.TITLE
        for page_value in document.pages
        for item in page_value.elements
    ) == 2


@pytest.mark.parametrize(
    ("route", "score", "warnings", "expected_status", "ready"),
    [
        (ParseRoute.FAST_NATIVE, 0.95, (), QualityStatus.PASS, True),
        (ParseRoute.FAST_NATIVE, 0.95, ("minor_warning",), QualityStatus.PASS_WITH_WARNINGS, True),
        (ParseRoute.FAST_NATIVE, 0.30, (), QualityStatus.RETRY_WITH_VLM, False),
        (ParseRoute.DOCUMENT_VLM, 0.20, (), QualityStatus.FAILED, False),
    ],
)
def test_quality_gate_controls_document_index_readiness(
    route: ParseRoute,
    score: float,
    warnings: tuple[str, ...],
    expected_status: QualityStatus,
    ready: bool,
) -> None:
    item = element("pymupdf-native-v2", ElementType.PARAGRAPH, "quality evidence", bbox(40, 100, 560, 160), 0, confidence=score)
    source_page = page("pymupdf-native-v2", route, (item,), score=score, warnings=warnings)
    document = reconcile(
        adapter_result("pymupdf-native-v2", (source_page,)),
        route_plan(route),
    )

    assert document.quality.status is expected_status
    assert document.quality.ready_for_index is ready
    assert QualityGate.is_ready(document.quality) is ready


def test_empty_low_quality_document_is_failed_and_cannot_enter_ready_index() -> None:
    source_page = page("pymupdf-native-v2", ParseRoute.DOCUMENT_VLM, (), score=0.0)
    document = reconcile(
        adapter_result("pymupdf-native-v2", (source_page,)),
        route_plan(ParseRoute.DOCUMENT_VLM),
    )

    assert document.pages[0].quality.status is QualityStatus.FAILED
    assert document.quality.status is QualityStatus.FAILED
    assert document.quality.ready_for_index is False
    assert document.quality.failed_pages == (1,)


def test_partial_layout_failure_retains_native_page_with_visible_warning() -> None:
    item = element("pymupdf-native-v2", ElementType.PARAGRAPH, "native fallback", bbox(40, 100, 560, 160), 0)
    native = adapter_result("pymupdf-native-v2", (page("pymupdf-native-v2", ParseRoute.LAYOUT_NATIVE, (item,)),))
    layout = adapter_result(
        "docling-layout-v2",
        (),
        selected=(1,),
        failed=(1,),
        warnings=("page_1:layout_model_failed",),
    )
    document = reconcile(native, route_plan(ParseRoute.LAYOUT_NATIVE), layout=layout)

    assert document.pages[0].elements[0].text == "native fallback"
    assert document.quality.status is QualityStatus.PASS_WITH_WARNINGS
    assert document.quality.ready_for_index is True
    assert "layout_model_failed" in " ".join(document.pages[0].quality.warnings)


def test_reconciliation_is_deterministic_and_every_final_element_has_accepted_provenance() -> None:
    native_item = element("pymupdf-native-v2", ElementType.PARAGRAPH, "stable", bbox(40, 100, 560, 160), 0)
    native = adapter_result("pymupdf-native-v2", (page("pymupdf-native-v2", ParseRoute.FAST_NATIVE, (native_item,)),))

    first = reconcile(native, route_plan(ParseRoute.FAST_NATIVE))
    second = reconcile(native, route_plan(ParseRoute.FAST_NATIVE))

    assert first.model_dump_json() == second.model_dump_json()
    assert all(
        element_value.provenance.parser_name
        and sum(candidate.accepted for candidate in element_value.source_candidates) == 1
        for page_value in first.pages
        for element_value in page_value.elements
    )


@pytest.mark.parametrize(
    "case_number",
    range(10),
)
def test_ten_bounded_candidate_fusion_samples_keep_rejected_summaries_bounded(
    case_number: int,
) -> None:
    box = bbox(40, 100 + case_number * 2, 560, 160 + case_number * 2)
    native_item = element("pymupdf-native-v2", ElementType.PARAGRAPH, f"sample {case_number}", box, 0)
    rejected_text = f"sample {case_number} " + "x" * 500
    vlm_item = element("paddleocr-vl-v2", ElementType.PARAGRAPH, rejected_text, box, 0)
    document = reconcile(
        adapter_result("pymupdf-native-v2", (page("pymupdf-native-v2", ParseRoute.FAST_NATIVE, (native_item,)),)),
        route_plan(ParseRoute.FAST_NATIVE),
        vlm=adapter_result("paddleocr-vl-v2", (page("paddleocr-vl-v2", ParseRoute.DOCUMENT_VLM, (vlm_item,)),)),
    )

    candidates = document.pages[0].elements[0].source_candidates
    assert len(candidates) == 2
    assert max(len(candidate.text) for candidate in candidates) <= 240
