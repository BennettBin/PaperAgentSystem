"""Read-only loader for exported online-system contracts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from training.contracts import ExportedBundleManifest


def load_exported_bundle(root: Path) -> tuple[ExportedBundleManifest, dict[str, Any]]:
    manifest_path = root / "manifest.json"
    manifest = ExportedBundleManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    manifest.validate_files(root)
    payload = {
        "agent_schema": json.loads((root / manifest.agent_schema).read_text(encoding="utf-8")),
        "tool_definitions": json.loads(
            (root / manifest.tool_definitions).read_text(encoding="utf-8")
        ),
        "training_sample_schema": json.loads(
            (root / manifest.training_sample_schema).read_text(encoding="utf-8")
        ),
    }
    return manifest, payload
