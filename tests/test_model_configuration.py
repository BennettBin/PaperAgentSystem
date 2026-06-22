import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from infrastructure.postgres.models import Base
from models.runtime import ModelRuntimeService


class FakeOllama:
    def __init__(self) -> None:
        self.installed = {"qwen3.5:4b"}
        self.pulled: list[str] = []
        self.probed: list[str] = []

    async def list_models(self) -> list[dict]:
        return [
            {
                "name": name,
                "size": 100,
                "details": {"parameter_size": "4.7B" if "4b" in name else "1.7B"},
                "capabilities": ["completion"],
            }
            for name in sorted(self.installed)
        ]

    async def pull(self, model: str) -> None:
        self.pulled.append(model)
        self.installed.add(model)

    async def probe(self, model: str) -> str:
        if model not in self.installed:
            raise RuntimeError("missing")
        self.probed.append(model)
        return "OK"


@pytest.fixture
def model_service(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'models.db').as_posix()}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    ollama = FakeOllama()
    return ModelRuntimeService(sessions, ollama), ollama


@pytest.mark.asyncio
async def test_defaults_use_base_models_and_report_missing_small_model(model_service):
    service, _ = model_service

    settings = await service.get_settings()

    assert settings["selected"]["small"]["stage"] == "base"
    assert settings["selected"]["large"]["stage"] == "base"
    small = next(item for item in settings["models"] if item["model_id"] == "base-qwen3-1.7b")
    large = next(item for item in settings["models"] if item["model_id"] == "base-qwen3.5-4b")
    assert small["installed"] is False
    assert large["installed"] is True


@pytest.mark.asyncio
async def test_missing_base_model_is_downloaded_probed_and_selected(model_service):
    service, ollama = model_service

    checked = await service.check_base_model("small", "qwen3:1.7b")
    assert checked["available"] is False
    assert checked["requires_download"] is True

    result = await service.download_and_select("small", "qwen3:1.7b")

    assert ollama.pulled == ["qwen3:1.7b"]
    assert ollama.probed == ["qwen3:1.7b"]
    assert result["selected"]["small"]["serving_model"] == "qwen3:1.7b"


@pytest.mark.asyncio
async def test_installed_other_base_can_be_selected_without_download(model_service):
    service, ollama = model_service
    ollama.installed.add("llama3.2:3b")

    checked = await service.check_base_model("small", "llama3.2:3b")
    result = await service.select("small", checked["model_id"])

    assert checked["available"] is True
    assert ollama.pulled == []
    assert result["selected"]["small"]["serving_model"] == "llama3.2:3b"
