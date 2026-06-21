"""Additional malicious file checks before parser dispatch."""

from __future__ import annotations

from core.errors import ErrorCode, ProjectError

MAX_UPLOAD_BYTES = 100 * 1024 * 1024


def validate_untrusted_file(
    filename: str,
    content_type: str,
    data: bytes,
    *,
    max_bytes: int = MAX_UPLOAD_BYTES,
) -> None:
    if len(data) > max_bytes:
        raise ProjectError(ErrorCode.RESOURCE_EXHAUSTED, "Uploaded file is too large")
    lower = filename.casefold()
    if lower.endswith((".exe", ".dll", ".bat", ".cmd", ".ps1", ".sh")):
        raise ProjectError(ErrorCode.UNSAFE_FILE_TYPE, "Executable uploads are not allowed")
    if data.startswith((b"MZ", b"\x7fELF")):
        raise ProjectError(ErrorCode.UNSAFE_FILE_TYPE, "Executable file signature detected")
    if content_type == "application/pdf" and not data.startswith(b"%PDF-"):
        raise ProjectError(ErrorCode.UNSAFE_FILE_TYPE, "PDF MIME/signature mismatch")
    if b"/JavaScript" in data or b"/Launch" in data:
        raise ProjectError(ErrorCode.UNSAFE_FILE_TYPE, "Active PDF content is not allowed")
