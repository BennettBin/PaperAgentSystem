import hashlib
from datetime import UTC, datetime
from io import BytesIO
from types import SimpleNamespace

import fitz
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.apps.api import product_service as product_service_module
from backend.apps.api.product_service import PaperAgentApplication, PaperAgentProcessor
from backend.apps.worker.fake_queue import FakeTaskQueue
from backend.core.errors import ProjectError
from backend.infrastructure.fake.adapters import FakeObjectStore
from backend.infrastructure.fake.llm_clients import FakeEmbeddingClient, FakeRerankerClient
from backend.infrastructure.fake.observability import FakeTraceWriter
from backend.infrastructure.postgres.models import (
    Base,
    ConversationFileModel,
    ConversationModel,
    DocumentChunkModel,
    DocumentSectionModel,
    FileModel,
    MessageModel,
    ParsedDocumentModel,
    UserModel,
    WorkspaceModel,
)
from backend.rag.indexing import CURRENT_INDEX_VERSION, CURRENT_SECTION_SCHEMA_VERSION


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


def _multi_section_pdf() -> bytes:
    document = fitz.open()
    sections = (
        ("1 Introduction", "The introduction defines the research problem."),
        (
            "2 Methods",
            "The method uses the PaperBench dataset and a structured agent runtime.",
        ),
        (
            "3 Results",
            "The results report improved citation support and lower retrieval errors.",
        ),
    )
    for heading, body in sections:
        page = document.new_page()
        page.insert_text((50, 60), heading, fontsize=16)
        page.insert_text((50, 105), body, fontsize=11)
        page.insert_text((50, 135), f"Additional evidence for {heading}.", fontsize=11)
    stream = BytesIO()
    document.save(stream)
    document.close()
    return stream.getvalue()


def _visual_pdf() -> bytes:
    document = fitz.open()
    page = document.new_page(width=600, height=800)
    page.insert_text((40, 70), "2 Methods", fontsize=16)
    page.insert_text((40, 105), "The method compares the main results.", fontsize=11)
    for x in (45, 145, 245):
        page.draw_line((x, 170), (x, 270), color=(0, 0, 0))
    for y in (170, 220, 270):
        page.draw_line((45, y), (245, y), color=(0, 0, 0))
    page.insert_text((65, 205), "CELL-HIDDEN-A", fontsize=10)
    page.insert_text((165, 205), "CELL-HIDDEN-B", fontsize=10)
    page.insert_text((45, 290), "Table 1: Main results", fontsize=10)
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


class ShortThenCompleteLLM(RecordingLLM):
    def __init__(self) -> None:
        super().__init__()
        self.prompts: list[str] = []

    async def generate(self, prompt: str, **_kwargs) -> str:
        self.prompts.append(prompt)
        self.prompt = prompt
        if len(self.prompts) == 1:
            return "这段"
        return "这段主要说明消融实验比较了模型不同组件对预测性能的影响。"


class InvalidCitationLLM(RecordingLLM):
    async def generate(self, prompt: str, **_kwargs) -> str:
        self.prompt = prompt
        return "模型回答引用了不存在的证据标签 [E99]，因此必须被验证器拒绝。"


class VisualAnswerLLM(RecordingLLM):
    async def generate(self, prompt: str, **_kwargs) -> str:
        self.prompt = prompt
        return "如 Table 1 所示，主要结果支持该结论 [E1]。"

    async def generate_with_schema(self, prompt: str, **_kwargs) -> str:
        return (
            '{"action":"retrieve","search_query":"Ablation Analysis",'
            '"section_hint":"Ablation Analysis","clarification_question":null}'
        )


class FollowUpLLM(RecordingLLM):
    async def generate_with_schema(self, prompt: str, **_kwargs) -> str:
        return (
            '{"action":"retrieve","search_query":"Ablation Analysis PaperBench",'
            '"section_hint":"Ablation Analysis","clarification_question":null}'
        )


class DatasetTopicLLM(RecordingLLM):
    async def generate_with_schema(self, prompt: str, **_kwargs) -> str:
        return (
            '{"action":"retrieve","search_query":"论文使用的数据集和验证",'
            '"section_hint":"数据集","clarification_question":null}'
        )


class EllipticalFollowUpLLM(RecordingLLM):
    async def generate_with_schema(self, prompt: str, **_kwargs) -> str:
        return (
            '{"action":"retrieve","search_query":"列举一下",'
            '"section_hint":"数据集","clarification_question":null}'
        )


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


@pytest.mark.asyncio
async def test_visual_artifacts_are_stored_with_layout_metadata_and_not_chunked(
    product_database,
) -> None:
    store = FakeObjectStore()
    data = _visual_pdf()
    object_key = await store.upload("uploads/visual.pdf", data, "application/pdf")
    with product_database() as session:
        session.add(
            FileModel(
                id="visual-file",
                workspace_id="local-workspace",
                filename="visual.pdf",
                content_type="application/pdf",
                size_bytes=len(data),
                storage_path=object_key,
                checksum=hashlib.sha256(data).hexdigest(),
                metadata_json={"parse_status": "queued"},
            )
        )
        session.commit()
    processor = PaperAgentProcessor(
        product_database,
        store,
        FakeEmbeddingClient(),
        FakeRerankerClient(),
        RecordingLLM(),
    )

    result = await processor.parse({"_task_id": "visual-parse", "file_id": "visual-file"})

    assert result["visual_artifacts"] == 1
    with product_database() as session:
        parsed = session.query(ParsedDocumentModel).one()
        artifact = parsed.metadata_json["visual_artifacts"][0]
        chunks = session.query(DocumentChunkModel).all()
        assert artifact["kind"] == "table"
        assert artifact["section_path"] == ["2 Methods"]
        assert artifact["storage_path"] in store.objects
        assert parsed.metadata_json["page_layouts"][0]["layout"] == "single_column"
        assert all("CELL-HIDDEN" not in chunk.text for chunk in chunks)
    application = PaperAgentApplication(product_database, store, FakeTaskQueue())
    image = await application.get_visual_artifact(artifact["artifact_id"])
    assert image["content_type"] == "image/png"
    assert image["data"].startswith(b"\x89PNG")


@pytest.mark.asyncio
async def test_follow_up_turn_injects_relevant_prior_questions_and_answers(
    product_database,
) -> None:
    with product_database() as session:
        _add_debug_index(session)
        session.add_all(
            [
                MessageModel(
                    id="prior-user",
                    workspace_id="local-workspace",
                    conversation_id="conversation-1",
                    role="user",
                    type="text",
                    content="这篇论文的主要方法是什么？",
                    metadata_json={},
                ),
                MessageModel(
                    id="prior-assistant",
                    workspace_id="local-workspace",
                    conversation_id="conversation-1",
                    role="assistant",
                    type="text",
                    content="该方法使用结构化 Agent runtime，并在 PaperBench 上评测。",
                    metadata_json={},
                ),
            ]
        )
        session.commit()
    llm = FollowUpLLM()
    processor = PaperAgentProcessor(
        product_database,
        FakeObjectStore(),
        FakeEmbeddingClient(),
        FakeRerankerClient(),
        llm,
    )

    await processor.answer(
        {
            "_task_id": "follow-up-task",
            "conversation_id": "conversation-1",
            "question": "它具体是怎么评测的？",
            "file_ids": ["file-debug"],
        }
    )

    assert "这篇论文的主要方法是什么" in llm.prompt
    assert "结构化 Agent runtime" in llm.prompt
    with product_database() as session:
        answer = session.scalars(
            select(MessageModel)
            .where(MessageModel.role == "assistant")
            .order_by(MessageModel.created_at.desc(), MessageModel.id.desc())
        ).first()
        assert answer is not None
        assert answer.metadata_json["rag"]["history_used"] is True
        assert set(answer.metadata_json["rag"]["history_source_message_ids"]) == {
            "prior-user",
            "prior-assistant",
        }


@pytest.mark.asyncio
async def test_dataset_topic_is_ordinary_rag_even_if_router_emits_section_hint(
    product_database,
) -> None:
    with product_database() as session:
        _add_debug_index(session)
        session.commit()
    llm = DatasetTopicLLM()
    processor = PaperAgentProcessor(
        product_database,
        FakeObjectStore(),
        FakeEmbeddingClient(),
        FakeRerankerClient(),
        llm,
    )

    result = await processor.answer(
        {
            "_task_id": "dataset-topic-task",
            "conversation_id": "conversation-1",
            "question": "告诉我这篇文章用了哪些数据集进行验证",
            "file_ids": ["file-debug"],
        }
    )

    assert result["status"] == "completed"
    assert "PaperBench" in llm.prompt
    with product_database() as session:
        answer = session.scalar(
            select(MessageModel).where(MessageModel.role == "assistant")
        )
        assert answer is not None
        assert answer.metadata_json["rag"]["retrieval_mode"] == "ordinary_rag"


@pytest.mark.asyncio
async def test_elliptical_follow_up_uses_prior_question_to_retrieve(
    product_database,
) -> None:
    with product_database() as session:
        _add_debug_index(session)
        session.add_all(
            [
                MessageModel(
                    id="dataset-user",
                    workspace_id="local-workspace",
                    conversation_id="conversation-1",
                    role="user",
                    type="text",
                    content="告诉我这篇文章用了哪些数据集进行验证",
                    metadata_json={},
                ),
                MessageModel(
                    id="dataset-assistant",
                    workspace_id="local-workspace",
                    conversation_id="conversation-1",
                    role="assistant",
                    type="text",
                    content="论文在 PaperBench 数据集上进行了验证。",
                    metadata_json={},
                ),
            ]
        )
        session.commit()
    llm = EllipticalFollowUpLLM()
    processor = PaperAgentProcessor(
        product_database,
        FakeObjectStore(),
        FakeEmbeddingClient(),
        FakeRerankerClient(),
        llm,
    )

    result = await processor.answer(
        {
            "_task_id": "elliptical-follow-up-task",
            "conversation_id": "conversation-1",
            "question": "列举一下",
            "file_ids": ["file-debug"],
        }
    )

    assert result["status"] == "completed"
    assert "告诉我这篇文章用了哪些数据集进行验证" in llm.prompt
    assert "PaperBench" in llm.prompt
    with product_database() as session:
        answer = session.scalars(
            select(MessageModel)
            .where(MessageModel.role == "assistant")
            .order_by(MessageModel.created_at.desc(), MessageModel.id.desc())
        ).first()
        assert answer is not None
        rag = answer.metadata_json["rag"]
        assert rag["history_used"] is True
        assert "数据集" in rag["query"]


@pytest.mark.asyncio
async def test_answer_that_mentions_table_includes_same_page_screenshot_metadata(
    product_database,
) -> None:
    with product_database() as session:
        _add_debug_index(session)
        parsed = session.query(ParsedDocumentModel).filter_by(id="document-debug").one()
        parsed.metadata_json = {
            **parsed.metadata_json,
            "visual_artifacts": [
                {
                    "artifact_id": "file-debug-p2-visual-1",
                    "kind": "table",
                    "label": "Table 1",
                    "caption": "Table 1: Ablation results",
                    "page_number": 2,
                    "bbox": {"x0": 10, "y0": 20, "x1": 300, "y1": 220},
                    "section_id": "sec-ablation",
                    "section_path": ["C. Ablation Analysis"],
                    "source_block_ids": ["b2"],
                    "storage_path": "artifacts/table-1.png",
                }
            ],
        }
        session.commit()
    processor = PaperAgentProcessor(
        product_database,
        FakeObjectStore(),
        FakeEmbeddingClient(),
        FakeRerankerClient(),
        VisualAnswerLLM(),
    )

    await processor.answer(
        {
            "_task_id": "visual-answer-task",
            "conversation_id": "conversation-1",
            "question": "Table 1 展示了什么？",
            "file_ids": ["file-debug"],
        }
    )

    with product_database() as session:
        answer = session.scalar(select(MessageModel).where(MessageModel.role == "assistant"))
        assert answer is not None
        visual = answer.metadata_json["visual_artifacts"][0]
        assert visual["label"] == "Table 1"
        assert visual["page"] == 2
        assert visual["image_url"].endswith("/file-debug-p2-visual-1/image")
@pytest.mark.asyncio
async def test_upload_reuses_soft_deleted_file_checksum(product_database):
    store = FakeObjectStore()
    queue = FakeTaskQueue()
    data = _paper_pdf()
    checksum = hashlib.sha256(data).hexdigest()
    deleted_at = datetime.now(UTC)
    with product_database() as session:
        session.add(
            FileModel(
                id="file-deleted",
                workspace_id="local-workspace",
                filename="old.pdf",
                content_type="application/pdf",
                size_bytes=1,
                storage_path="uploads/deleted.pdf",
                checksum=checksum,
                is_deleted=True,
                reference_count=0,
                deleted_at=deleted_at,
                metadata_json={"parse_status": "deleted"},
            )
        )
        session.add(
            ConversationFileModel(
                id="link-deleted",
                workspace_id="local-workspace",
                conversation_id="conversation-1",
                file_id="file-deleted",
                deleted_at=deleted_at,
            )
        )
        session.commit()

    application = PaperAgentApplication(product_database, store, queue)

    result = await application.upload_file(
        "conversation-1",
        "paper.pdf",
        "application/pdf",
        data,
    )

    assert result["id"] == "file-deleted"
    assert result["parse_status"] == "queued"
    assert len(store.objects) == 1
    with product_database() as session:
        files = session.scalars(select(FileModel)).all()
        assert [file.id for file in files] == ["file-deleted"]
        file_model = session.get(FileModel, "file-deleted")
        link = session.get(ConversationFileModel, "link-deleted")
        assert file_model is not None
        assert file_model.is_deleted is False
        assert file_model.deleted_at is None
        assert file_model.reference_count == 1
        assert file_model.filename == "paper.pdf"
        assert file_model.storage_path in store.objects
        assert link is not None
        assert link.deleted_at is None


@pytest.mark.asyncio
async def test_short_model_answer_is_retried_before_saving(product_database):
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
                checksum="b" * 64,
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

    llm = ShortThenCompleteLLM()
    processor = PaperAgentProcessor(
        product_database,
        store,
        FakeEmbeddingClient(),
        FakeRerankerClient(),
        llm,
    )

    result = await processor.answer(
        {
            "_task_id": "task-short",
            "conversation_id": "conversation-1",
            "question": "C. Ablation Analysis 这一届的每一段讲了什么？",
            "file_ids": ["file-1"],
        }
    )

    assert result["status"] == "completed"
    assert len(llm.prompts) == 2
    with product_database() as session:
        assistant = session.scalar(
            select(MessageModel).where(MessageModel.role == "assistant")
        )
        assert assistant is not None
        assert assistant.content.startswith("这段主要说明")


@pytest.mark.asyncio
async def test_delete_conversation_removes_history_files_and_indexes(product_database):
    store = FakeObjectStore()
    data = _paper_pdf()
    object_key = await store.upload("uploads/paper.pdf", data, "application/pdf")
    artifact_key = await store.upload(
        "artifacts/pdf-visuals/table-delete.png",
        b"\x89PNG\r\n\x1a\nfixture",
        "image/png",
    )
    with product_database() as session:
        session.add(
            FileModel(
                id="file-delete",
                workspace_id="local-workspace",
                filename="paper.pdf",
                content_type="application/pdf",
                size_bytes=len(data),
                storage_path=object_key,
                checksum="c" * 64,
                metadata_json={"parse_status": "parsed"},
            )
        )
        session.add(
            ConversationFileModel(
                id="link-delete",
                workspace_id="local-workspace",
                conversation_id="conversation-1",
                file_id="file-delete",
            )
        )
        session.add(
            MessageModel(
                id="message-delete",
                workspace_id="local-workspace",
                conversation_id="conversation-1",
                role="user",
                type="text",
                content="delete me",
            )
        )
        session.add(
            ParsedDocumentModel(
                id="document-delete",
                workspace_id="local-workspace",
                file_id="file-delete",
                checksum="c" * 64,
                parser_name="fixture",
                parser_version="1",
                page_count=1,
                quality_score=100,
                metadata_json={
                    "visual_artifacts": [{"storage_path": artifact_key}],
                },
            )
        )
        session.add(
            DocumentSectionModel(
                id="section-delete",
                workspace_id="local-workspace",
                file_id="file-delete",
                document_id="document-delete",
                section_id="s1",
                number="1",
                title="Methods",
                normalized_title="methods",
                level=1,
                parent_section_id=None,
                section_path=["Methods"],
                ordinal=1,
                page_start=1,
                page_end=1,
                heading_block_id="b1",
            )
        )
        session.add(
            DocumentChunkModel(
                id="chunk-delete",
                workspace_id="local-workspace",
                file_id="file-delete",
                document_id="document-delete",
                parent_chunk_id=None,
                level="child",
                section_id="s1",
                section_path=["Methods"],
                text="PaperBench evidence",
                page_start=1,
                page_end=1,
                bbox_json=[0, 0, 100, 100],
                source_block_ids=["b1"],
                embedding=[0.0] * 1024,
                embedding_model="fixture",
                searchable_text="PaperBench evidence",
            )
        )
        session.commit()

    application = PaperAgentApplication(product_database, store, FakeTaskQueue())

    result = await application.delete_conversation("conversation-1")

    assert result["deleted"] is True
    assert result["deleted_file_count"] == 1
    assert not await store.exists(object_key)
    assert not await store.exists(artifact_key)
    assert await application.list_conversations() == []
    assert await application.list_files() == []
    with product_database() as session:
        assert session.get(ConversationModel, "conversation-1").deleted_at is not None
        assert session.get(FileModel, "file-delete").is_deleted is True
        assert session.get(MessageModel, "message-delete").deleted_at is not None
        assert session.get(ParsedDocumentModel, "document-delete") is None
        assert session.get(DocumentSectionModel, "section-delete") is None
        assert session.get(DocumentChunkModel, "chunk-delete") is None


def _add_debug_index(session) -> None:
    session.add(
        FileModel(
            id="file-debug",
            workspace_id="local-workspace",
            filename="debug.pdf",
            content_type="application/pdf",
            size_bytes=100,
            storage_path="uploads/debug.pdf",
            checksum="d" * 64,
            metadata_json={"parse_status": "parsed"},
        )
    )
    session.add(
        ConversationFileModel(
            id="link-debug",
            workspace_id="local-workspace",
            conversation_id="conversation-1",
            file_id="file-debug",
        )
    )
    session.add(
        ParsedDocumentModel(
            id="document-debug",
            workspace_id="local-workspace",
            file_id="file-debug",
            checksum="d" * 64,
            parser_name="fixture",
            parser_version="1",
            page_count=3,
            quality_score=99,
            metadata_json={
                "index_version": CURRENT_INDEX_VERSION,
                "section_schema_version": CURRENT_SECTION_SCHEMA_VERSION,
            },
        )
    )
    session.add(
        DocumentSectionModel(
            id="section-debug",
            workspace_id="local-workspace",
            file_id="file-debug",
            document_id="document-debug",
            section_id="sec-ablation",
            number="C",
            title="Ablation Analysis",
            normalized_title="ablation analysis",
            level=1,
            parent_section_id=None,
            section_path=["C. Ablation Analysis"],
            ordinal=1,
            page_start=2,
            page_end=3,
            heading_block_id="b1",
            block_ids=["b1", "b2"],
            descendant_block_ids=["b1", "b2"],
        )
    )
    session.add(
        DocumentChunkModel(
            id="chunk-debug",
            workspace_id="local-workspace",
            file_id="file-debug",
            document_id="document-debug",
            parent_chunk_id=None,
            level="child",
            section_id="sec-ablation",
            section_title="Ablation Analysis",
            section_path=["C. Ablation Analysis"],
            chunk_index_in_section=0,
            text="Ablation Analysis compares each component and reports PaperBench gains.",
            page_start=2,
            page_end=2,
            bbox_json=[0, 0, 100, 100],
            source_block_ids=["b2"],
            embedding=[0.2] * 1024,
            embedding_model="multilingual-hash-v1",
            searchable_text="Ablation Analysis compares each component and reports PaperBench gains.",
        )
    )


@pytest.mark.asyncio
async def test_debug_parse_result_exports_sections_and_chunks(
    product_database, tmp_path, monkeypatch
):
    monkeypatch.setattr(
        product_service_module,
        "DIAGNOSTIC_EXPORT_DIR",
        tmp_path / "rag_diagnostics",
    )
    with product_database() as session:
        _add_debug_index(session)
        session.commit()
    application = PaperAgentApplication(
        product_database,
        FakeObjectStore(),
        FakeTaskQueue(),
    )

    result = await application.debug_parse_result("file-debug")

    assert result["sections"][0]["title"] == "Ablation Analysis"
    assert result["chunks"][0]["chunk_id"] == "chunk-debug"
    assert (tmp_path / "rag_diagnostics" / "parse_file-debug.json").exists()
    assert (tmp_path / "rag_diagnostics" / "parse_file-debug.md").exists()


@pytest.mark.asyncio
async def test_debug_retrieval_preview_returns_stage_hits_and_exports(
    product_database, tmp_path, monkeypatch
):
    monkeypatch.setattr(
        product_service_module,
        "DIAGNOSTIC_EXPORT_DIR",
        tmp_path / "rag_diagnostics",
    )
    with product_database() as session:
        _add_debug_index(session)
        session.commit()
    application = PaperAgentApplication(
        product_database,
        FakeObjectStore(),
        FakeTaskQueue(),
    )

    result = await application.debug_retrieval_preview(
        "conversation-1",
        "C. Ablation Analysis 这一节讲了什么",
        ["file-debug"],
    )

    assert result["parsed_section_hint"] == "Ablation Analysis"
    assert result["section_hits"][0]["chunk_id"] == "chunk-debug"
    assert result["bm25_hits"][0]["chunk_id"] == "chunk-debug"
    assert result["final_context_sent_to_llm"][0]["chunk_id"] == "chunk-debug"
    assert list((tmp_path / "rag_diagnostics").glob("retrieval_conversation-1_*.json"))


@pytest.mark.asyncio
async def test_explicit_missing_section_requests_clarification_without_fallback(
    product_database,
) -> None:
    with product_database() as session:
        _add_debug_index(session)
        session.commit()
    llm = RecordingLLM()
    processor = PaperAgentProcessor(
        product_database,
        FakeObjectStore(),
        FakeEmbeddingClient(),
        FakeRerankerClient(),
        llm,
    )

    result = await processor.answer(
        {
            "_task_id": "missing-section-task",
            "conversation_id": "conversation-1",
            "question": "请总结第 7.3 节",
            "file_ids": ["file-debug"],
        }
    )

    assert result["status"] == "waiting_user"
    assert "7.3" in result["question"]
    assert llm.prompt == ""


@pytest.mark.asyncio
async def test_resolved_section_summary_metadata_is_persisted(product_database) -> None:
    with product_database() as session:
        _add_debug_index(session)
        session.commit()
    llm = RecordingLLM()
    processor = PaperAgentProcessor(
        product_database,
        FakeObjectStore(),
        FakeEmbeddingClient(),
        FakeRerankerClient(),
        llm,
    )

    result = await processor.answer(
        {
            "_task_id": "section-summary-task",
            "conversation_id": "conversation-1",
            "question": "请总结 Ablation Analysis section",
            "file_ids": ["file-debug"],
        }
    )

    assert result["status"] == "completed"
    with product_database() as session:
        assistant = session.scalar(
            select(MessageModel).where(MessageModel.role == "assistant")
        )
        assert assistant is not None
        rag = assistant.metadata_json["rag"]
        assert rag["retrieval_mode"] == "section_summary"
        assert rag["selected_section_id"] == "sec-ablation"
        assert rag["scope_section_ids"] == ["sec-ablation"]


@pytest.mark.asyncio
async def test_product_rag_trace_contains_only_safe_structured_metadata(
    product_database,
) -> None:
    with product_database() as session:
        _add_debug_index(session)
        session.commit()
    traces = FakeTraceWriter()
    processor = PaperAgentProcessor(
        product_database,
        FakeObjectStore(),
        FakeEmbeddingClient(),
        FakeRerankerClient(),
        RecordingLLM(),
        trace_writer=traces,
    )

    await processor.answer(
        {
            "_task_id": "safe-trace-task",
            "conversation_id": "conversation-1",
            "question": "请总结 Ablation Analysis section",
            "file_ids": ["file-debug"],
        }
    )

    names = [trace["span_name"] for trace in traces.traces]
    assert "agent.react" in names
    assert "rag.retrieve" in names
    assert "verification.complete" in names
    assert "task.completed" in names
    serialized = str(traces.traces)
    assert "请总结" not in serialized
    assert "Ablation Analysis compares" not in serialized


@pytest.mark.asyncio
async def test_unknown_model_citation_is_rejected_before_answer_is_saved(
    product_database,
) -> None:
    with product_database() as session:
        _add_debug_index(session)
        session.commit()
    traces = FakeTraceWriter()
    processor = PaperAgentProcessor(
        product_database,
        FakeObjectStore(),
        FakeEmbeddingClient(),
        FakeRerankerClient(),
        InvalidCitationLLM(),
        trace_writer=traces,
    )

    with pytest.raises(ProjectError):
        await processor.answer(
            {
                "_task_id": "invalid-citation-task",
                "conversation_id": "conversation-1",
                "question": "请总结 Ablation Analysis section",
                "file_ids": ["file-debug"],
            }
        )

    with product_database() as session:
        assert session.scalar(
            select(MessageModel).where(MessageModel.role == "assistant")
        ) is None
    verification = [
        trace
        for trace in traces.traces
        if trace["span_name"] == "verification.complete"
    ]
    assert verification[-1]["data"]["passed"] is False


@pytest.mark.asyncio
async def test_old_index_is_rebuilt_during_real_multisection_pdf_e2e(
    product_database,
) -> None:
    store = FakeObjectStore()
    data = _multi_section_pdf()
    checksum = hashlib.sha256(data).hexdigest()
    object_key = await store.upload(
        "uploads/multi-section.pdf", data, "application/pdf"
    )
    with product_database() as session:
        session.add(
            FileModel(
                id="multi-file",
                workspace_id="local-workspace",
                filename="multi-section.pdf",
                content_type="application/pdf",
                size_bytes=len(data),
                storage_path=object_key,
                checksum=checksum,
                metadata_json={"parse_status": "parsed"},
            )
        )
        session.add(
            ConversationFileModel(
                id="multi-link",
                workspace_id="local-workspace",
                conversation_id="conversation-1",
                file_id="multi-file",
            )
        )
        session.add(
            ParsedDocumentModel(
                id="old-index",
                workspace_id="local-workspace",
                file_id="multi-file",
                checksum=checksum,
                parser_name="legacy",
                parser_version="0",
                page_count=3,
                quality_score=80,
                metadata_json={
                    "index_version": CURRENT_INDEX_VERSION - 1,
                    "section_schema_version": CURRENT_SECTION_SCHEMA_VERSION,
                },
            )
        )
        session.add(
            DocumentSectionModel(
                id="old-section-row",
                workspace_id="local-workspace",
                file_id="multi-file",
                document_id="old-index",
                section_id="old-section",
                number="2",
                title="Legacy Methods",
                normalized_title="legacy methods",
                level=1,
                parent_section_id=None,
                section_path=["2 Legacy Methods"],
                ordinal=0,
                page_start=1,
                page_end=1,
                heading_block_id="old-heading",
            )
        )
        session.add(
            DocumentChunkModel(
                id="old-chunk",
                workspace_id="local-workspace",
                file_id="multi-file",
                document_id="old-index",
                parent_chunk_id=None,
                level="child",
                section_id="old-section",
                section_number="2",
                section_title="Legacy Methods",
                section_path=["2 Legacy Methods"],
                chunk_index_in_section=0,
                text="stale evidence must not survive reindexing",
                page_start=1,
                page_end=1,
                bbox_json=[0, 0, 100, 100],
                source_block_ids=["old-block"],
                embedding=[0.0] * 1024,
                embedding_model="multilingual-hash-v1",
                searchable_text="stale evidence must not survive reindexing",
            )
        )
        session.commit()
    traces = FakeTraceWriter()
    llm = RecordingLLM()
    processor = PaperAgentProcessor(
        product_database,
        store,
        FakeEmbeddingClient(),
        FakeRerankerClient(),
        llm,
        trace_writer=traces,
    )

    result = await processor.answer(
        {
            "_task_id": "multisection-e2e-task",
            "conversation_id": "conversation-1",
            "question": "请总结第 2 节",
            "file_ids": ["multi-file"],
        }
    )

    assert result["status"] == "completed"
    assert "stale evidence" not in llm.prompt
    assert "PaperBench" in llm.prompt
    with product_database() as session:
        documents = session.query(ParsedDocumentModel).all()
        assert len(documents) == 1
        assert documents[0].id != "old-index"
        assert documents[0].metadata_json["index_version"] == CURRENT_INDEX_VERSION
        assistant = session.scalar(
            select(MessageModel).where(MessageModel.role == "assistant")
        )
        assert assistant is not None
        evidence = assistant.metadata_json["evidence"]
        assert evidence
        assert all(item["page"] == 2 for item in evidence)
        assert all("2 Methods" in item["section"] for item in evidence)
    index_spans = [
        trace for trace in traces.traces if trace["span_name"] == "document.index"
    ]
    assert index_spans[-1]["data"]["reindexed"] is True


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
