from io import BytesIO
from types import SimpleNamespace

import fitz
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from apps.api.product_service import PaperAgentApplication, PaperAgentProcessor
from apps.worker.fake_queue import FakeTaskQueue
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

    async def generate_with_schema(self, prompt: str, **_kwargs) -> str:
        return (
            '{"action":"retrieve","search_query":"PaperBench dataset",'
            '"section_hint":"Methods","clarification_question":null}'
        )


class UsageRecordingLLM(RecordingLLM):
    last_usage = SimpleNamespace(
        input_tokens=40,
        output_tokens=10,
        total_tokens=50,
    )
    last_model_name = "fixture-model"


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
        assert assistant.metadata_json["evidence"][0]["quote"]
        assert assistant.metadata_json["evidence"][0]["page"] == 1
        assert assistant.metadata_json["rag"]["used"] is True


class ClarifyingLLM(RecordingLLM):
    def __init__(self) -> None:
        super().__init__()
        self.decisions = 0

    async def generate_with_schema(self, prompt: str, **_kwargs) -> str:
        self.decisions += 1
        if self.decisions == 1:
            return (
                '{"action":"clarify","search_query":null,"section_hint":null,'
                '"clarification_question":"你希望分析哪个章节？"}'
            )
        return (
            '{"action":"retrieve","search_query":"Methods PaperBench",'
            '"section_hint":"Methods","clarification_question":null}'
        )


@pytest.mark.asyncio
async def test_clarification_answer_resumes_previous_request(product_database):
    store = FakeObjectStore()
    llm = ClarifyingLLM()
    processor = PaperAgentProcessor(
        product_database,
        store,
        FakeEmbeddingClient(),
        FakeRerankerClient(),
        llm,
        decision_llm=llm,
    )

    first = await processor.answer(
        {
            "_task_id": "root-task",
            "conversation_id": "conversation-1",
            "question": "帮我深入分析一下",
            "file_ids": [],
        }
    )

    assert first["status"] == "waiting_user"
    with product_database() as session:
        clarification = session.scalar(
            select(MessageModel).where(MessageModel.role == "assistant")
        )
        assert clarification is not None
        assert clarification.metadata_json["kind"] == "clarification"
        assert clarification.metadata_json["original_request"] == "帮我深入分析一下"


@pytest.mark.asyncio
async def test_application_requeues_the_same_waiting_task_after_user_answer(
    product_database,
):
    store = FakeObjectStore()
    queue = FakeTaskQueue()
    root_task_id = await queue.enqueue(
        "main_agent",
        {
            "conversation_id": "conversation-1",
            "question": "深入分析论文",
            "file_ids": [],
        },
        "root-task",
    )
    with product_database() as session:
        session.add(
            MessageModel(
                id="clarification-message",
                workspace_id="local-workspace",
                conversation_id="conversation-1",
                role="assistant",
                type="clarification",
                content="你希望分析哪个章节？",
                metadata_json={
                    "kind": "clarification",
                    "root_task_id": root_task_id,
                    "original_request": "深入分析论文",
                    "file_ids": [],
                    "clarification_round": 1,
                    "resolved": False,
                },
            )
        )
        session.commit()
    application = PaperAgentApplication(product_database, store, queue)

    result = await application.submit_message(
        "conversation-1", "实验章节", []
    )

    assert result["task_id"] == root_task_id
    assert result["resumed"] is True
    resumed_task = queue.tasks[root_task_id]
    assert resumed_task.payload["question"] == "深入分析论文"
    assert resumed_task.payload["clarification_answer"] == "实验章节"


@pytest.mark.asyncio
async def test_conversation_usage_aggregates_small_and_large_model_tokens(
    product_database,
):
    store = FakeObjectStore()
    data = _paper_pdf()
    object_key = await store.upload("uploads/usage.pdf", data, "application/pdf")
    with product_database() as session:
        session.add(
            FileModel(
                id="usage-file",
                workspace_id="local-workspace",
                filename="usage.pdf",
                content_type="application/pdf",
                size_bytes=len(data),
                storage_path=object_key,
                checksum="b" * 64,
                metadata_json={"parse_status": "queued"},
            )
        )
        session.add(
            ConversationFileModel(
                id="usage-link",
                workspace_id="local-workspace",
                conversation_id="conversation-1",
                file_id="usage-file",
            )
        )
        session.commit()
    llm = UsageRecordingLLM()
    processor = PaperAgentProcessor(
        product_database,
        store,
        FakeEmbeddingClient(),
        FakeRerankerClient(),
        llm,
        decision_llm=llm,
    )
    await processor.answer(
        {
            "_task_id": "usage-task",
            "conversation_id": "conversation-1",
            "question": "论文使用了什么数据集？",
            "file_ids": ["usage-file"],
        }
    )
    application = PaperAgentApplication(product_database, store, FakeTaskQueue())

    usage = await application.conversation_usage("conversation-1")

    assert usage["small"]["total_tokens"] == 50
    assert usage["large"]["total_tokens"] == 50
    assert usage["total"]["total_tokens"] == 100
