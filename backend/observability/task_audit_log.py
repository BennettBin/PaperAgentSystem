"""Per-task JSONL audit logs for safe operational diagnosis."""

from __future__ import annotations

import json
import re
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_SAFE_TASK_ID = re.compile(r"[^A-Za-z0-9._-]+")
_SAFE_DETAIL_KEYS = {
    "action",
    "artifact_count",
    "artifact_id",
    "chunk_count",
    "conversation_id",
    "event_type",
    "evidence_count",
    "file_count",
    "file_id",
    "file_ids",
    "filename",
    "message_id",
    "model_role",
    "page_count",
    "reindexed",
    "retrieval_mode",
    "section_hint_present",
    "skill_name",
    "stage",
    "storage_path",
    "title",
}


class JsonlTaskAuditLogWriter:
    """Append allow-listed metadata to one UTF-8 JSONL file per task."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def append(
        self,
        task_id: str,
        action: str,
        *,
        component: str,
        status: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        safe_id = _SAFE_TASK_ID.sub("_", task_id).strip("._") or "unknown-task"
        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            "task_id": task_id,
            "action": action,
            "component": component,
            "status": status,
            "details": _safe_details(details or {}),
        }
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            with (self.root / f"{safe_id}.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(f"{line}\n")


def _safe_details(details: dict[str, Any]) -> dict[str, Any]:
    return {
        str(key): value
        for key, value in details.items()
        if str(key) in _SAFE_DETAIL_KEYS and _safe_value(value)
    }


def _safe_value(value: Any) -> bool:
    if value is None or isinstance(value, (str, int, float, bool)):
        return True
    return isinstance(value, list) and all(
        item is None or isinstance(item, (str, int, float, bool)) for item in value
    )
