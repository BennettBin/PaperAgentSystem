"""Export the authoritative metric catalog as reviewable Markdown."""

from __future__ import annotations

import argparse
from pathlib import Path

from evaluation.metrics.catalog import CORE_METRICS, MetricCategory


def render_catalog_markdown() -> str:
    lines = [
        "# PaperAgent L03 Metric Catalog",
        "",
        "This file is generated from `evaluation.metrics.catalog`. The Python catalog is the executable truth.",
        "Format/schema validity metrics are diagnostic and must never replace task correctness.",
        "",
    ]
    for category in MetricCategory:
        definitions = [item for item in CORE_METRICS.values() if item.category is category]
        lines.extend(
            [
                f"## {category.value}",
                "",
                "| Metric | Direction | Unit | Formula | Denominator | Applicability | Outlier handling |",
                "|---|---|---|---|---|---|---|",
            ]
        )
        for item in definitions:
            cells = (
                item.name.value,
                item.direction.value,
                item.unit,
                item.formula,
                item.denominator,
                item.applicability,
                item.outlier_handling,
            )
            escaped = [cell.replace("|", "\\|").replace("\n", " ") for cell in cells]
            lines.append("| " + " | ".join(escaped) + " |")
        lines.append("")
    lines.extend(
        [
            "## Statistical reporting",
            "",
            "- Absolute values use the metric-specific statistic above.",
            "- Main metrics report seeded percentile-bootstrap 95% confidence intervals.",
            "- Candidate-vs-baseline comparisons require paired `case_id` values and use paired bootstrap deltas.",
            "- Undefined denominators are excluded and reported; they are never coerced to zero.",
            "- Reports retain dataset/config/model/Profile/Prompt versions and Judge provenance.",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export L03 metric catalog")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_catalog_markdown(), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
