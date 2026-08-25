"""Parser-neutral ports for the hybrid document processing pipeline."""

from __future__ import annotations

from abc import ABC, abstractmethod

from backend.document_processing.schema_v2 import (
    AdapterParseResult,
    CanonicalDocumentV2,
    PageSelection,
    ParsingContext,
)


class PageParserAdapter(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def version(self) -> str: ...

    @abstractmethod
    async def supports_format(self, filename: str) -> bool: ...

    @abstractmethod
    async def parse_pages(
        self,
        file_data: bytes,
        filename: str,
        selection: PageSelection,
        context: ParsingContext,
    ) -> AdapterParseResult: ...


class DocumentLayoutAdapter(PageParserAdapter):
    """Port for non-generative layout-aware document parsing such as Docling."""


class DocumentVLMAdapter(PageParserAdapter):
    """Port for bounded document-specialized VLM page parsing."""


class OfficeDocumentAdapter(ABC):
    """Port for approved Office formats with non-PDF locator semantics."""

    @abstractmethod
    async def supports_format(self, filename: str) -> bool: ...

    @abstractmethod
    async def parse(
        self,
        file_data: bytes,
        filename: str,
        *,
        context: ParsingContext,
    ) -> CanonicalDocumentV2: ...


class DocumentParsingPipeline(ABC):
    @abstractmethod
    async def parse(
        self,
        file_data: bytes,
        filename: str,
        *,
        trace_id: str,
    ) -> CanonicalDocumentV2: ...
