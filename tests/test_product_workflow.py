from io import BytesIO

import fitz
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from apps.api.product_service import PaperAgentProcessor
from infrastructure.fake.adapters import FakeObjectStore
from infrastructure.fake.llm_clients import FakeEmbeddingClient, FakeRerankerClient
from infrastructure.postgres.models import (
    Base,
    ConversationFileModel,
    ConversationModel,
    FileModel,
    MessageModel,
    UserModel,
    WorkspaceModel,
)


def _paper_pdf() -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((50, 60), "Methods", fontsize=16)
    page.insert_text(
        (50, 100),
        "The study uses the PaperBench dataset and reports 92 percent accuracy.",
        fontsize=11,
    )
    stream = BytesIO()
    document.save(stream)
    document.close()
    return stream.getvalue()


class RecordingLLM:
    def __init__(self) -> None:
        self.prompt = ""

    async def generate(self, prompt: str, **_kwargs) -> str:
        self.prompt = prompt
        return "模型回答：论文使用 PaperBench 数据集。"


@pytest.fixture
def product_database(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'product.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as session:
        session.add(UserModel(id="local-user", email="local@example.test", name="Local"))
        session.add(
            WorkspaceModel(
                id="local-workspace",
                user_id="local-user",
                name="Local workspace",
            )
        )
        session.add(
            ConversationModel(
                id="conversation-1",
                workspace_id="local-workspace",
                user_id="local-user",
                title="Paper QA",
            )
        )
        session.commit()
    return factory


@pytest.mark.asyncio
async def test_uploaded_pdf_is_parsed_retrieved_and_passed_to_model(product_database):
    store = FakeObjectStore()
    data = _paper_pdf()
    object_key = await store.upload("uploads/paper.pdf", data, "application/pdf")
    with product_database() as session:
        session.add(
            FileModel(
                id="file-1",
                workspace_id="local-workspace",
                filename="paper.pdf",
                content_type="application/pdf",
                size_bytes=len(data),
                storage_path=object_key,
                checksum="a" * 64,
                metadata_json={"parse_status": "queued"},
            )
        )
        session.add(
            ConversationFileModel(
                id="link-1",
                workspace_id="local-workspace",
                conversation_id="conversation-1",
                file_id="file-1",
            )
        )
        session.commit()

    llm = RecordingLLM()
    processor = PaperAgentProcessor(
        product_database,
        store,
        FakeEmbeddingClient(),
        FakeRerankerClient(),
        llm,
    )

    result = await processor.answer(
        {
            "_task_id": "task-1",
            "conversation_id": "conversation-1",
            "question": "这篇论文使用了什么数据集？",
            "file_ids": ["file-1"],
        }
    )

    assert result["status"] == "completed"
    assert "PaperBench" in llm.prompt
    with product_database() as session:
        assistant = session.scalar(
            select(MessageModel).where(MessageModel.role == "assistant")
        )
        file_model = session.get(FileModel, "file-1")
        assert assistant is not None
        assert "模型回答" in assistant.content
        assert file_model is not None
        assert file_model.metadata_json["parse_status"] == "parsed"

