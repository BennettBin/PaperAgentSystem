"""Paper parsing and OCR services with cycle-safe lazy public exports."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from backend.document_processing.adaptive_pipeline import (
        AdaptiveDocumentPipeline,
        AdaptiveParseDiagnostics,
        AdaptiveParseOutcome,
        ProductionDocumentPipeline,
        ProductionParseOutcome,
    )
    from backend.document_processing.docling_adapter import DoclingLayoutAdapter
    from backend.document_processing.markdown_v2 import (
        CanonicalMarkdownRenderer,
        DerivedMarkdownV2,
    )
    from backend.document_processing.office_adapter import DoclingOfficeAdapter
    from backend.document_processing.paddleocr_vl_adapter import PaddleOCRVLAdapter
    from backend.document_processing.reconciler import QualityGate, ResultReconciler
    from backend.document_processing.schema_v2 import CanonicalDocumentV2

__all__ = [
    "AdaptiveDocumentPipeline",
    "AdaptiveParseDiagnostics",
    "AdaptiveParseOutcome",
    "CanonicalDocumentV2",
    "CanonicalMarkdownRenderer",
    "DerivedMarkdownV2",
    "DoclingLayoutAdapter",
    "DoclingOfficeAdapter",
    "PaddleOCRVLAdapter",
    "QualityGate",
    "ResultReconciler",
    "ProductionDocumentPipeline",
    "ProductionParseOutcome",
]

_EXPORTS = {
    "AdaptiveDocumentPipeline": (
        "backend.document_processing.adaptive_pipeline",
        "AdaptiveDocumentPipeline",
    ),
    "AdaptiveParseDiagnostics": (
        "backend.document_processing.adaptive_pipeline",
        "AdaptiveParseDiagnostics",
    ),
    "AdaptiveParseOutcome": (
        "backend.document_processing.adaptive_pipeline",
        "AdaptiveParseOutcome",
    ),
    "CanonicalDocumentV2": ("backend.document_processing.schema_v2", "CanonicalDocumentV2"),
    "CanonicalMarkdownRenderer": (
        "backend.document_processing.markdown_v2",
        "CanonicalMarkdownRenderer",
    ),
    "DerivedMarkdownV2": (
        "backend.document_processing.markdown_v2",
        "DerivedMarkdownV2",
    ),
    "DoclingLayoutAdapter": ("backend.document_processing.docling_adapter", "DoclingLayoutAdapter"),
    "DoclingOfficeAdapter": (
        "backend.document_processing.office_adapter",
        "DoclingOfficeAdapter",
    ),
    "PaddleOCRVLAdapter": ("backend.document_processing.paddleocr_vl_adapter", "PaddleOCRVLAdapter"),
    "QualityGate": ("backend.document_processing.reconciler", "QualityGate"),
    "ResultReconciler": ("backend.document_processing.reconciler", "ResultReconciler"),
    "ProductionDocumentPipeline": (
        "backend.document_processing.adaptive_pipeline",
        "ProductionDocumentPipeline",
    ),
    "ProductionParseOutcome": (
        "backend.document_processing.adaptive_pipeline",
        "ProductionParseOutcome",
    ),
}


def __getattr__(name: str) -> Any:
    try:
        module_name, attribute_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value
