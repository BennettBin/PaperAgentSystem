from __future__ import annotations

import hashlib

import pytest
from pydantic import ValidationError

from backend.core.ports.document_processing import (
    DocumentLayoutAdapter,
    DocumentParsingPipeline,
)
from backend.document_processing.schema_v2 import (
    AdapterParseResult,
    CanonicalBoundingBox,
    CanonicalDocumentV2,
    CanonicalPage,
    DocumentElement,
    DocumentQuality,
    ElementType,
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
    ReconciliationDecision,
    SourceCandidate,
    canonical_json,
    stable_document_id,
    stable_element_id,
)

CHECKSUM = hashlib.sha256(b"paperagent-v2-contract").hexdigest()


def pipeline_descriptor(*, parser_version: str = "1.0", threshold: int = 20) -> PipelineDescriptor:
    return PipelineDescriptor(
        router_version="router-v1",
        render_scale=2.0,
        components=(
            PipelineComponent(
                name="fixture-parser",
                version=parser_version,
                config={"threshold": threshold, "enabled": True},
            ),
        ),
        config={"maximum_pages": 30},
    )


def quality() -> PageQuality:
    return PageQuality(
        status=QualityStatus.PASS,
        overall=1,
        text=1,
        coordinates=1,
        reading_order=1,
        structure=1,
        ocr=1,
        tables=1,
        completeness=1,
    )


def element(*, page_number: int = 1, inferred: bool = False) -> DocumentElement:
    bbox = CanonicalBoundingBox(x0=10, y0=20, x1=200, y1=50)
    element_id = stable_element_id(
        CHECKSUM,
        page_number,
        ElementType.PARAGRAPH,
        0,
        bbox,
        "Traceable evidence",
    )
    provenance = ParserProvenance(
        parser_name="fixture-parser",
        parser_version="1.0",
        confidence=0.99,
        source_coordinate_space="pdf_point",
        is_inferred=inferred,
    )
    normalized_bbox = NormalizedBoundingBox(
        x0=10 / 600, y0=20 / 800, x1=200 / 600, y1=50 / 800,
    )
    return DocumentElement(
        element_id=element_id,
        page_number=page_number,
        element_type=ElementType.PARAGRAPH,
        text="Traceable evidence",
        normalized_text="Traceable evidence",
        bbox=bbox,
        normalized_bbox=normalized_bbox,
        reading_order=0,
        provenance=provenance,
        source_candidates=(SourceCandidate(
            candidate_id="cand_fixture",
            element_type=ElementType.PARAGRAPH,
            text="Traceable evidence",
            bbox=bbox,
            normalized_bbox=normalized_bbox,
            reading_order=0,
            provenance=provenance,
            accepted=True,
            decision_reason="fixture accepted",
        ),),
        is_inferred=inferred,
    )


def page(*, page_number: int = 1) -> CanonicalPage:
    profile = PageProfile(
        page_number=page_number,
        native_character_count=18,
        garble_ratio=0,
        image_coverage=0,
        text_overlap_ratio=0,
        bbox_out_of_bounds_ratio=0,
        detected_column_count=1,
        proposed_route=ParseRoute.FAST_NATIVE,
    )
    return CanonicalPage(
        page_number=page_number,
        width=600,
        height=800,
        cropbox=CanonicalBoundingBox(x0=0, y0=0, x1=600, y1=800),
        selected_route=ParseRoute.FAST_NATIVE,
        profile=profile,
        elements=(element(page_number=page_number),),
        quality=quality(),
    )


def document() -> CanonicalDocumentV2:
    pipeline = pipeline_descriptor()
    page_value = page()
    element_value = page_value.elements[0]
    return CanonicalDocumentV2(
        document_id=stable_document_id(CHECKSUM),
        filename="paper.pdf",
        checksum=CHECKSUM,
        page_count=1,
        pipeline=pipeline,
        pipeline_fingerprint=pipeline.fingerprint,
        pages=(page_value,),
        reconciliation_decisions=(ReconciliationDecision(
            decision_id="decision_000000000000000000000000",
            page_number=1,
            output_element_id=element_value.element_id,
            accepted_candidate_id="cand_fixture",
            reason="fixture accepted",
            confidence=0.99,
        ),),
        quality=DocumentQuality(status=QualityStatus.PASS, overall=1),
    )


def test_canonical_bbox_rejects_reversed_or_negative_coordinates() -> None:
    with pytest.raises(ValidationError):
        CanonicalBoundingBox(x0=20, y0=0, x1=10, y1=30)
    with pytest.raises(ValidationError):
        CanonicalBoundingBox(x0=-1, y0=0, x1=10, y1=30)


def test_normalized_bbox_rejects_coordinates_outside_unit_square() -> None:
    with pytest.raises(ValidationError):
        NormalizedBoundingBox(x0=0, y0=0, x1=1.01, y1=1)


def test_pipeline_fingerprint_is_stable_across_mapping_order() -> None:
    left = PipelineDescriptor(
        router_version="router-v1",
        render_scale=2,
        components=(
            PipelineComponent(name="parser", version="1", config={"b": 2, "a": 1}),
        ),
        config={"z": False, "a": True},
    )
    right = PipelineDescriptor(
        router_version="router-v1",
        render_scale=2,
        components=(
            PipelineComponent(name="parser", version="1", config={"a": 1, "b": 2}),
        ),
        config={"a": True, "z": False},
    )

    assert left.fingerprint == right.fingerprint
    assert canonical_json(left) == canonical_json(right)


def test_pipeline_fingerprint_changes_with_parser_or_config() -> None:
    original = pipeline_descriptor()

    assert original.fingerprint != pipeline_descriptor(parser_version="2.0").fingerprint
    assert original.fingerprint != pipeline_descriptor(threshold=21).fingerprint


def test_stable_element_id_normalizes_whitespace_but_preserves_position() -> None:
    bbox = CanonicalBoundingBox(x0=1, y0=2, x1=3, y1=4)
    first = stable_element_id(CHECKSUM, 1, ElementType.PARAGRAPH, 0, bbox, "a   b")
    second = stable_element_id(CHECKSUM, 1, ElementType.PARAGRAPH, 0, bbox, "a b")
    moved = stable_element_id(CHECKSUM, 2, ElementType.PARAGRAPH, 0, bbox, "a b")

    assert first == second
    assert first != moved


def test_page_rejects_element_from_another_page() -> None:
    valid = page()
    with pytest.raises(ValidationError, match="element page number"):
        valid.model_copy(update={"elements": (element(page_number=2),)}, deep=True).__class__(
            **valid.model_copy(update={"elements": (element(page_number=2),)}).model_dump()
        )


def test_document_rejects_mismatched_pipeline_fingerprint() -> None:
    valid = document()
    payload = valid.model_dump()
    payload["pipeline_fingerprint"] = "0" * 64

    with pytest.raises(ValidationError, match="pipeline fingerprint"):
        CanonicalDocumentV2.model_validate(payload)


def test_document_rejects_non_contiguous_pages() -> None:
    valid = document()
    payload = valid.model_dump()
    payload["page_count"] = 1
    payload["pages"] = [page(page_number=2).model_dump()]

    with pytest.raises(ValidationError, match="contiguous"):
        CanonicalDocumentV2.model_validate(payload)


def test_document_element_inferred_flag_must_match_provenance() -> None:
    payload = element(inferred=True).model_dump()
    payload["is_inferred"] = False

    with pytest.raises(ValidationError, match="inferred flags"):
        DocumentElement.model_validate(payload)


def test_canonical_document_json_round_trip_is_stable() -> None:
    original = document()
    serialized = canonical_json(original)
    restored = CanonicalDocumentV2.model_validate_json(serialized)

    assert restored == original
    assert canonical_json(restored) == serialized


def test_page_selection_requires_sorted_unique_one_based_pages() -> None:
    assert PageSelection(page_numbers=(1, 3)).page_numbers == (1, 3)
    with pytest.raises(ValidationError):
        PageSelection(page_numbers=(3, 1))
    with pytest.raises(ValidationError):
        PageSelection(page_numbers=(1, 1))
    with pytest.raises(ValidationError):
        PageSelection(page_numbers=(0,))


class FakeLayoutAdapter(DocumentLayoutAdapter):
    @property
    def name(self) -> str:
        return "fake-layout"

    @property
    def version(self) -> str:
        return "1.0"

    async def supports_format(self, filename: str) -> bool:
        return filename.casefold().endswith(".pdf")

    async def parse_pages(
        self,
        file_data: bytes,
        filename: str,
        selection: PageSelection,
        context: ParsingContext,
    ) -> AdapterParseResult:
        return AdapterParseResult(
            parser_name=self.name,
            parser_version=self.version,
            selection=selection,
            pages=(page(),),
        )


class FakePipeline(DocumentParsingPipeline):
    async def parse(
        self,
        file_data: bytes,
        filename: str,
        *,
        trace_id: str,
    ) -> CanonicalDocumentV2:
        return document()


@pytest.mark.asyncio
async def test_parser_ports_share_the_strong_v2_contract() -> None:
    pipeline = pipeline_descriptor()
    context = ParsingContext(
        trace_id="trace-v2",
        document_checksum=CHECKSUM,
        pipeline=pipeline,
        timeout_seconds=30,
    )
    adapter = FakeLayoutAdapter()

    assert await adapter.supports_format("paper.PDF") is True
    result = await adapter.parse_pages(
        b"pdf",
        "paper.pdf",
        PageSelection(page_numbers=(1,)),
        context,
    )
    parsed = await FakePipeline().parse(b"pdf", "paper.pdf", trace_id="trace-v2")

    assert result.pages[0].elements[0].text == "Traceable evidence"
    assert parsed.pipeline_fingerprint == pipeline.fingerprint


def test_schema_forbids_unknown_fields() -> None:
    payload = document().model_dump()
    payload["unexpected"] = True

    with pytest.raises(ValidationError, match="Extra inputs"):
        CanonicalDocumentV2.model_validate(payload)
