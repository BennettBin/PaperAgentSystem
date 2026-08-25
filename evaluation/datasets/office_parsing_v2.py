"""Deterministic bounded OOXML corpus for PDF-V11 contract tests."""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


@dataclass(frozen=True, slots=True)
class OfficeSample:
    case_id: str
    filename: str
    content_type: str
    data: bytes
    locator_type: str
    expected_locator_count: int


def office_v2_corpus() -> tuple[OfficeSample, ...]:
    """Return 12 small native-text samples: six DOCX and six PPTX."""

    samples: list[OfficeSample] = []
    for index in range(6):
        paragraphs = (f"DOCX sample {index} title", f"Native paragraph {index}")
        samples.append(
            OfficeSample(
                case_id=f"office-docx-{index:02d}",
                filename=f"sample-{index:02d}.docx",
                content_type=DOCX_MIME,
                data=build_docx(paragraphs),
                locator_type="docx_position",
                expected_locator_count=len(paragraphs),
            )
        )
    for index in range(6):
        slide_count = 1 + (index % 2)
        samples.append(
            OfficeSample(
                case_id=f"office-pptx-{index:02d}",
                filename=f"slides-{index:02d}.pptx",
                content_type=PPTX_MIME,
                data=build_pptx(tuple(f"Native slide {index}-{slide}" for slide in range(1, slide_count + 1))),
                locator_type="pptx_slide",
                expected_locator_count=slide_count,
            )
        )
    return tuple(samples)


def build_docx(paragraphs: tuple[str, ...]) -> bytes:
    body = "".join(
        f"<w:p><w:r><w:t>{_xml_escape(text)}</w:t></w:r></w:p>" for text in paragraphs
    )
    return _archive(
        {
            "[Content_Types].xml": (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                '<Override PartName="/word/document.xml" '
                'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                "</Types>"
            ),
            "_rels/.rels": (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
                'Target="word/document.xml"/>'
                "</Relationships>"
            ),
            "word/document.xml": (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                f"<w:body>{body}</w:body></w:document>"
            ),
        }
    )


def build_pptx(slide_texts: tuple[str, ...]) -> bytes:
    overrides = "".join(
        '<Override PartName="/ppt/slides/slide{number}.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
        .format(number=number)
        for number in range(1, len(slide_texts) + 1)
    )
    entries = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Override PartName="/ppt/presentation.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>'
            f"{overrides}</Types>"
        ),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
            'Target="ppt/presentation.xml"/>'
            "</Relationships>"
        ),
        "ppt/presentation.xml": (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"/>'
        ),
    }
    for number, text in enumerate(slide_texts, 1):
        entries[f"ppt/slides/slide{number}.xml"] = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
            'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
            f"<p:cSld><a:t>{_xml_escape(text)}</a:t></p:cSld></p:sld>"
        )
    return _archive(entries)


def _archive(entries: dict[str, str]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, value in sorted(entries.items()):
            info = zipfile.ZipInfo(name, date_time=(2024, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            archive.writestr(info, value.encode("utf-8"))
    return output.getvalue()


def _xml_escape(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
