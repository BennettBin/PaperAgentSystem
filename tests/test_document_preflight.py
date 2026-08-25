from __future__ import annotations

from io import BytesIO

import fitz
import pytest

from backend.core.errors import ErrorCode, ProjectError
from backend.document_processing.config import DocumentProcessingConfig
from backend.document_processing.preflight import PDFPreflight


def make_pdf(*, pages: int = 1, width: float = 612, height: float = 792) -> bytes:
    document = fitz.open()
    for page_number in range(1, pages + 1):
        page = document.new_page(width=width, height=height)
        page.insert_text((40, 60), f"Page {page_number} traceable text", fontsize=11)
    stream = BytesIO()
    document.save(stream, no_new_id=True)
    document.close()
    return stream.getvalue()


def encrypted_pdf() -> bytes:
    document = fitz.open()
    document.new_page().insert_text((40, 60), "Protected evidence")
    stream = BytesIO()
    document.save(
        stream,
        encryption=fitz.PDF_ENCRYPT_AES_256,
        owner_pw="owner-password",
        user_pw="user-password",
        no_new_id=True,
    )
    document.close()
    return stream.getvalue()


def assert_error(
    data: bytes,
    *,
    code: ErrorCode,
    config: DocumentProcessingConfig | None = None,
    filename: str = "paper.pdf",
) -> ProjectError:
    with pytest.raises(ProjectError) as captured:
        PDFPreflight(config).inspect(data, filename)
    assert captured.value.code is code
    return captured.value


def test_preflight_returns_hash_pages_dimensions_and_pixel_budget() -> None:
    result = PDFPreflight().inspect(make_pdf(pages=2), "paper.pdf")

    assert result.detected_format == "pdf"
    assert result.page_count == 2
    assert len(result.checksum) == 64
    assert [page.page_number for page in result.pages] == [1, 2]
    assert result.total_estimated_render_pixels == sum(
        page.estimated_render_pixels for page in result.pages
    )
    assert all(page.width == 612 and page.height == 792 for page in result.pages)


def test_preflight_rejects_non_pdf_filename_and_signature() -> None:
    assert_error(make_pdf(), code=ErrorCode.UNSAFE_FILE_TYPE, filename="paper.docx")
    assert_error(b"not a pdf", code=ErrorCode.UNSAFE_FILE_TYPE)


def test_preflight_rejects_corrupt_pdf_after_valid_signature() -> None:
    assert_error(b"%PDF-1.7\ncorrupted", code=ErrorCode.PARSING_FAILED)


def test_preflight_rejects_encrypted_pdf_without_logging_password() -> None:
    error = assert_error(encrypted_pdf(), code=ErrorCode.FAILED_PRECONDITION)

    assert error.details == {"reason": "encrypted_pdf"}
    assert "password" in error.message.casefold()
    assert "owner-password" not in str(error.to_dict())


def test_preflight_enforces_file_and_page_count_limits() -> None:
    assert_error(
        make_pdf(),
        code=ErrorCode.RESOURCE_EXHAUSTED,
        config=DocumentProcessingConfig(max_file_bytes=16),
    )
    page_error = assert_error(
        make_pdf(pages=2),
        code=ErrorCode.RESOURCE_EXHAUSTED,
        config=DocumentProcessingConfig(max_pages=1),
    )
    assert page_error.details["page_count"] == 2


def test_preflight_enforces_page_dimension_limit() -> None:
    error = assert_error(
        make_pdf(width=700),
        code=ErrorCode.RESOURCE_EXHAUSTED,
        config=DocumentProcessingConfig(max_page_width_points=650),
    )

    assert error.details["page_number"] == 1
    assert error.details["width"] == 700


def test_preflight_enforces_per_page_render_pixel_limit() -> None:
    error = assert_error(
        make_pdf(),
        code=ErrorCode.RESOURCE_EXHAUSTED,
        config=DocumentProcessingConfig(
            max_render_pixels_per_page=1_000_000,
            max_render_pixels_per_document=2_000_000,
        ),
    )

    assert error.details["estimated_pixels"] > error.details["max_pixels"]


def test_preflight_enforces_total_render_pixel_limit() -> None:
    error = assert_error(
        make_pdf(pages=2),
        code=ErrorCode.RESOURCE_EXHAUSTED,
        config=DocumentProcessingConfig(
            max_render_pixels_per_page=2_000_000,
            max_render_pixels_per_document=3_000_000,
        ),
    )

    assert error.details["estimated_pixels"] > error.details["max_pixels"]


def test_preflight_reuses_active_pdf_content_security_gate() -> None:
    malicious = make_pdf() + b"\n/JavaScript"

    assert_error(malicious, code=ErrorCode.UNSAFE_FILE_TYPE)

