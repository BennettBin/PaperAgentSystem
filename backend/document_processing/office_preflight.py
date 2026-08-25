"""Bounded, non-extracting OOXML preflight for approved Office formats."""

from __future__ import annotations

import hashlib
import io
import stat
import zipfile
from pathlib import PurePosixPath
from xml.etree import ElementTree

from pydantic import BaseModel, ConfigDict, Field

from backend.core.errors import ErrorCode, ProjectError
from backend.document_processing.schema_v2 import LocatorType

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
_FORMAT_BY_SUFFIX = {
    ".docx": (DOCX_MIME, "word/document.xml", LocatorType.DOCX_POSITION),
    ".pptx": (PPTX_MIME, "ppt/presentation.xml", LocatorType.PPTX_SLIDE),
}


class OfficePreflightResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_type: str
    locator_type: LocatorType
    native_locator_count: int = Field(ge=1)
    archive_entry_count: int = Field(ge=1)
    uncompressed_size: int = Field(ge=1)


class OfficePreflight:
    """Validate an OOXML ZIP without extracting it or following relationships."""

    def __init__(
        self,
        *,
        max_entries: int = 2_000,
        max_uncompressed_bytes: int = 256 * 1024 * 1024,
        max_compression_ratio: float = 200.0,
    ) -> None:
        self._max_entries = max_entries
        self._max_uncompressed_bytes = max_uncompressed_bytes
        self._max_compression_ratio = max_compression_ratio

    def inspect(
        self,
        file_data: bytes,
        filename: str,
        content_type: str | None = None,
    ) -> OfficePreflightResult:
        suffix = PurePosixPath(filename.casefold()).suffix
        expected = _FORMAT_BY_SUFFIX.get(suffix)
        if expected is None:
            raise ProjectError(ErrorCode.UNSAFE_FILE_TYPE, "Only DOCX and PPTX are approved")
        expected_mime, required_main, locator_type = expected
        if content_type is not None and content_type != expected_mime:
            raise ProjectError(ErrorCode.UNSAFE_FILE_TYPE, "Office MIME and extension do not match")
        if not file_data.startswith(b"PK"):
            raise ProjectError(ErrorCode.UNSAFE_FILE_TYPE, "Office file is not an OOXML ZIP")
        try:
            archive = zipfile.ZipFile(io.BytesIO(file_data))
        except (zipfile.BadZipFile, OSError) as exc:
            raise ProjectError(ErrorCode.PARSING_FAILED, "Invalid OOXML package", cause=exc) from exc
        with archive:
            infos = archive.infolist()
            if not infos or len(infos) > self._max_entries:
                raise ProjectError(ErrorCode.RESOURCE_EXHAUSTED, "OOXML entry limit exceeded")
            names: set[str] = set()
            total_uncompressed = 0
            total_compressed = 0
            for info in infos:
                self._validate_entry(info)
                if info.filename in names:
                    raise ProjectError(ErrorCode.UNSAFE_FILE_TYPE, "Duplicate OOXML entry")
                names.add(info.filename)
                total_uncompressed += info.file_size
                total_compressed += max(1, info.compress_size)
            if total_uncompressed > self._max_uncompressed_bytes:
                raise ProjectError(ErrorCode.RESOURCE_EXHAUSTED, "OOXML expanded-size limit exceeded")
            if total_uncompressed / max(1, total_compressed) > self._max_compression_ratio:
                raise ProjectError(ErrorCode.RESOURCE_EXHAUSTED, "OOXML compression-ratio limit exceeded")
            required = {"[Content_Types].xml", "_rels/.rels", required_main}
            if not required <= names:
                raise ProjectError(ErrorCode.UNSAFE_FILE_TYPE, "OOXML package is missing required parts")
            self._reject_external_relationships(archive, names)
            locator_count = self._locator_count(archive, suffix, names)
        return OfficePreflightResult(
            checksum=hashlib.sha256(file_data).hexdigest(),
            content_type=expected_mime,
            locator_type=locator_type,
            native_locator_count=locator_count,
            archive_entry_count=len(infos),
            uncompressed_size=total_uncompressed,
        )

    @staticmethod
    def _validate_entry(info: zipfile.ZipInfo) -> None:
        path = PurePosixPath(info.filename)
        if (
            path.is_absolute()
            or ".." in path.parts
            or "\\" in info.filename
            or info.flag_bits & 0x1
        ):
            raise ProjectError(ErrorCode.UNSAFE_FILE_TYPE, "Unsafe OOXML archive entry")
        mode = info.external_attr >> 16
        if mode and stat.S_ISLNK(mode):
            raise ProjectError(ErrorCode.UNSAFE_FILE_TYPE, "OOXML symlinks are forbidden")

    @staticmethod
    def _reject_external_relationships(archive: zipfile.ZipFile, names: set[str]) -> None:
        for name in sorted(item for item in names if item.casefold().endswith(".rels")):
            try:
                root = ElementTree.fromstring(archive.read(name))
            except (ElementTree.ParseError, KeyError) as exc:
                raise ProjectError(ErrorCode.UNSAFE_FILE_TYPE, "Invalid OOXML relationships") from exc
            for relationship in root.iter():
                if relationship.attrib.get("TargetMode", "").casefold() == "external":
                    raise ProjectError(
                        ErrorCode.UNSAFE_FILE_TYPE,
                        "External OOXML relationships are forbidden",
                    )

    @staticmethod
    def _locator_count(archive: zipfile.ZipFile, suffix: str, names: set[str]) -> int:
        if suffix == ".pptx":
            slides = [
                name
                for name in names
                if name.startswith("ppt/slides/slide") and name.endswith(".xml")
            ]
            if not slides:
                raise ProjectError(ErrorCode.UNSAFE_FILE_TYPE, "PPTX contains no slides")
            return len(slides)
        try:
            root = ElementTree.fromstring(archive.read("word/document.xml"))
        except (ElementTree.ParseError, KeyError) as exc:
            raise ProjectError(ErrorCode.UNSAFE_FILE_TYPE, "Invalid DOCX main document") from exc
        paragraph_count = sum(1 for node in root.iter() if node.tag.endswith("}p"))
        if paragraph_count < 1:
            raise ProjectError(ErrorCode.UNSAFE_FILE_TYPE, "DOCX contains no structural positions")
        return paragraph_count
