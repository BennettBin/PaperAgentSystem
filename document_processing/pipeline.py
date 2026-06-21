"""Trace-compatible parsing pipeline composition."""

from document_processing.pdf_parser import PyMuPDFParser
from document_processing.schema import ParsedDocument


class BasicPDFPipeline:
    def __init__(self, parser: PyMuPDFParser | None = None) -> None:
        self._parser = parser or PyMuPDFParser()

    async def parse(
        self,
        file_data: bytes,
        filename: str,
        *,
        trace_id: str,
    ) -> ParsedDocument:
        return await self._parser.parse(file_data, filename)
