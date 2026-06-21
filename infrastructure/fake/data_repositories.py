"""
Fake Memory Repository implementation
"""

from typing import Optional, List, Any
from core.domain.ids import WorkspaceId


class FakeMemoryRepository:
    def __init__(self):
        self.segments: dict[str, Any] = {}

    async def save_segment(self, segment_id: str, content: str, workspace_id: WorkspaceId) -> None:
        self.segments[segment_id] = {"content": content, "workspace_id": str(workspace_id)}

    async def find_segment(self, segment_id: str, workspace_id: WorkspaceId) -> Optional[dict]:
        seg = self.segments.get(segment_id)
        if seg and seg["workspace_id"] == str(workspace_id):
            return seg
        return None

    async def search_segments(self, query: str, workspace_id: WorkspaceId, top_k: int = 5) -> List[dict]:
        return [s for s in self.segments.values() if s["workspace_id"] == str(workspace_id)][:top_k]

    async def delete_segment(self, segment_id: str, workspace_id: WorkspaceId) -> bool:
        seg = self.segments.pop(segment_id, None)
        return seg is not None and seg["workspace_id"] == str(workspace_id)


class FakeDocumentRepository:
    def __init__(self):
        self.documents: dict[str, Any] = {}

    async def save_document(self, doc_id: str, content: dict, workspace_id: WorkspaceId) -> None:
        self.documents[doc_id] = {"content": content, "workspace_id": str(workspace_id)}

    async def find_document(self, doc_id: str, workspace_id: WorkspaceId) -> Optional[dict]:
        doc = self.documents.get(doc_id)
        if doc and doc["workspace_id"] == str(workspace_id):
            return doc
        return None

    async def delete_document(self, doc_id: str, workspace_id: WorkspaceId) -> bool:
        doc = self.documents.pop(doc_id, None)
        return doc is not None and doc["workspace_id"] == str(workspace_id)
