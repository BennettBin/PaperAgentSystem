"""Deterministic Markdown projection derived from CanonicalDocument V2 JSON."""

from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import Field

from backend.document_processing.schema_v2 import (
    CanonicalDocumentV2,
    ElementType,
    FrozenModel,
    StructuredTable,
)


class DerivedMarkdownV2(FrozenModel):
    schema_version: Literal["2.0"] = "2.0"
    document_id: str = Field(pattern=r"^doc_[0-9a-f]{24}$")
    pipeline_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    content: str
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class CanonicalMarkdownRenderer:
    """Render a reproducible view; CanonicalDocumentV2 remains the source of truth."""

    def render(self, document: CanonicalDocumentV2) -> DerivedMarkdownV2:
        tables_by_element = {
            source_id: table
            for table in document.tables
            for source_id in table.source_element_ids
        }
        equations_by_element = {
            source_id: equation
            for equation in document.equations
            for source_id in equation.source_element_ids
        }
        figures_by_element = {
            source_id: figure
            for figure in document.figures
            for source_id in figure.source_element_ids
        }
        lines = [
            "<!-- canonical-document-v2; derived view; JSON is authoritative -->",
            f"<!-- pipeline-fingerprint: {document.pipeline_fingerprint} -->",
            "",
        ]
        rendered_tables: set[str] = set()
        rendered_equations: set[str] = set()
        rendered_figures: set[str] = set()
        for page in document.pages:
            lines.extend((f"<!-- page: {page.page_number} -->", ""))
            for element in page.elements:
                lines.append(f'<a id="{element.element_id}"></a>')
                if element.element_type is ElementType.TABLE_CELL:
                    lines.append("")
                    continue
                if element.element_type is ElementType.TABLE:
                    table = tables_by_element.get(element.element_id)
                    if table is not None and table.table_id not in rendered_tables:
                        lines.extend((*self._table_markdown(table), ""))
                        rendered_tables.add(table.table_id)
                    continue
                if element.element_type is ElementType.EQUATION:
                    equation = equations_by_element.get(element.element_id)
                    if equation is not None and equation.equation_id not in rendered_equations:
                        if equation.number:
                            lines.append(f"Equation {equation.number}")
                        lines.extend(("$$", equation.latex, "$$", ""))
                        rendered_equations.add(equation.equation_id)
                    continue
                if element.element_type is ElementType.FIGURE:
                    figure = figures_by_element.get(element.element_id)
                    if figure is not None and figure.figure_id not in rendered_figures:
                        if figure.caption:
                            lines.append(f"**{figure.caption}**")
                        if figure.description:
                            label = "[inferred description] " if figure.description_is_inferred else ""
                            lines.append(f"> {label}{figure.description}")
                        lines.append("")
                        rendered_figures.add(figure.figure_id)
                    continue
                rendered = self._text_element(element.element_type, element.text)
                if rendered:
                    lines.extend((rendered, ""))
        content = "\n".join(lines).rstrip() + "\n"
        return DerivedMarkdownV2(
            document_id=document.document_id,
            pipeline_fingerprint=document.pipeline_fingerprint,
            content=content,
            content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        )

    @staticmethod
    def _text_element(element_type: ElementType, text: str) -> str:
        if not text.strip():
            return ""
        if element_type is ElementType.TITLE:
            return f"# {text}"
        if element_type is ElementType.SECTION_HEADING:
            return f"## {text}"
        if element_type is ElementType.LIST_ITEM:
            return f"- {text}"
        if element_type is ElementType.CAPTION:
            return f"*{text}*"
        if element_type in {ElementType.PAGE_HEADER, ElementType.PAGE_FOOTER}:
            return f"<!-- {element_type.value}: {text} -->"
        return text

    @staticmethod
    def _table_markdown(table: StructuredTable) -> tuple[str, ...]:
        if table.markdown.strip():
            body = tuple(table.markdown.strip().splitlines())
        elif table.cells:
            row_count = max(cell.row_index for cell in table.cells) + 1
            column_count = max(cell.column_index for cell in table.cells) + 1
            grid = [["" for _ in range(column_count)] for _ in range(row_count)]
            for cell in table.cells:
                grid[cell.row_index][cell.column_index] = cell.text.replace("|", "\\|")
            body = tuple(
                [
                    "| " + " | ".join(grid[0]) + " |",
                    "| " + " | ".join("---" for _ in range(column_count)) + " |",
                    *("| " + " | ".join(row) + " |" for row in grid[1:]),
                ]
            )
        else:
            body = ("| |", "| --- |")
        return (*((f"**{table.caption}**",) if table.caption else ()), *body)
