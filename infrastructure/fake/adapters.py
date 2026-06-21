"""
Fake Storage, Registry and Processing adapters
"""

from io import BytesIO
from typing import Any, Dict, List, Optional

from core.ports.processing import ClaimVerifier, DocumentParser, Retriever, SandboxExecutor
from core.ports.registry import ModelRegistry, SkillRegistry, ToolRegistry
from core.ports.storage import EventPublisher, ObjectStore


class FakeObjectStore(ObjectStore):
    def __init__(self):
        self.objects: Dict[str, bytes] = {}

    async def upload(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> str:
        self.objects[key] = data
        return key

    async def upload_stream(
        self, key: str, stream: BytesIO, content_type: str = "application/octet-stream"
    ) -> str:
        self.objects[key] = stream.getvalue()
        return key

    async def download(self, key: str) -> bytes:
        if key not in self.objects:
            raise FileNotFoundError(f"Object not found: {key}")
        return self.objects[key]

    async def download_stream(self, key: str) -> BytesIO:
        if key not in self.objects:
            raise FileNotFoundError(f"Object not found: {key}")
        return BytesIO(self.objects[key])

    async def delete(self, key: str) -> None:
        self.objects.pop(key, None)

    async def exists(self, key: str) -> bool:
        return key in self.objects

    async def get_temporary_url(self, key: str, expires_in_seconds: int = 3600) -> str:
        return f"http://fake-minio/{key}"


class FakeEventPublisher(EventPublisher):
    def __init__(self):
        self.events: List[Any] = []

    async def publish(self, event_type: str, data: dict, channel: Optional[str] = None) -> None:
        self.events.append({"type": event_type, "data": data, "channel": channel})

    async def subscribe(self, channel: str) -> list[dict]:
        return [event for event in self.events if event["channel"] == channel]


class FakeToolDefinition:
    """Fake ToolDefinition implementation"""

    def __init__(self, name: str, description: str, parameters_schema: dict):
        self._name = name
        self._description = description
        self._parameters_schema = parameters_schema

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def parameters_schema(self) -> dict:
        return self._parameters_schema


class FakeToolRegistry(ToolRegistry):
    def __init__(self):
        self.tools: Dict[str, FakeToolDefinition] = {}

    async def register(self, tool) -> None:
        self.tools[tool.name] = tool

    async def get(self, tool_name: str) -> Optional[Any]:
        return self.tools.get(tool_name)

    async def list_all(self) -> list:
        return list(self.tools.values())

    async def verify_access(self, tool_name: str, permissions: list[str]) -> bool:
        return tool_name in self.tools


class FakeSkillDefinition:
    """Fake SkillDefinition implementation"""

    def __init__(self, name: str, description: str, required_tools: list, model_profile: str):
        self._name = name
        self._description = description
        self._required_tools = required_tools
        self._model_profile = model_profile

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def required_tools(self) -> list[str]:
        return self._required_tools

    @property
    def model_profile(self) -> str:
        return self._model_profile


class FakeSkillRegistry(SkillRegistry):
    def __init__(self):
        self.skills: Dict[str, FakeSkillDefinition] = {}

    async def register(self, skill) -> None:
        self.skills[skill.name] = skill

    async def get(self, skill_name: str) -> Optional[Any]:
        return self.skills.get(skill_name)

    async def list_all(self) -> list:
        return list(self.skills.values())


class FakeModelProfile:
    """Fake ModelProfile implementation"""

    def __init__(self, name: str, status: str, context_length: int):
        self.profile_id = name
        self.name = name
        self.status = status
        self.context_length = context_length
        self.max_tokens = min(2048, context_length)
        self.config: dict = {}


class FakeModelRegistry(ModelRegistry):
    def __init__(self):
        self.profiles: Dict[str, FakeModelProfile] = {
            "development": FakeModelProfile("development", "active", 4096),
            "production": FakeModelProfile("production", "active", 8192),
        }

    async def get_profile(self, profile_name: str) -> Optional[Any]:
        return self.profiles.get(profile_name)

    async def list_profiles(self) -> list:
        return list(self.profiles.values())

    async def register_profile(self, profile: Any) -> None:
        self.profiles[profile.name] = profile

    async def get_default_profile(self) -> Any:
        return self.profiles["development"]


class FakeDocumentParser(DocumentParser):
    async def parse(self, file_data: bytes, filename: str) -> dict:
        return {
            "text": "Fake parsed document content",
            "chunks": [{"text": "chunk 1", "page": 0}, {"text": "chunk 2", "page": 1}],
            "metadata": {"filename": filename, "pages": 2},
        }

    async def supports_format(self, filename: str) -> bool:
        return filename.lower().endswith((".pdf", ".txt", ".docx"))


class FakeRetriever(Retriever):
    async def search(
        self, query: str, top_k: int = 10, workspace_id: Optional[str] = None
    ) -> List[dict]:
        return [
            {"doc_id": "doc-1", "score": 0.95, "text": "Relevant content 1"},
            {"doc_id": "doc-2", "score": 0.87, "text": "Relevant content 2"},
        ]

    async def index(self, doc_id: str, text: str, metadata: dict) -> None:
        pass

    async def delete_index(self, doc_id: str) -> None:
        return None


class FakeClaimVerifier(ClaimVerifier):
    async def verify_claim(self, claim: str, evidence: List[str]) -> dict:
        return {
            "claim": claim,
            "is_supported": True,
            "confidence": 0.85,
            "evidence_used": evidence,
        }


class FakeSandboxExecutor(SandboxExecutor):
    async def execute_code(
        self, code: str, language: str = "python", timeout_seconds: int = 30
    ) -> dict:
        return {
            "success": False,
            "error": "Code execution not supported in this environment",
            "output": "",
        }

    async def render_latex(self, latex_code: str) -> bytes:
        return b"%PDF-fake"
