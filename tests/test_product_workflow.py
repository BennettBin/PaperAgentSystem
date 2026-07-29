import hashlib
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import fitz
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.agent_runtime.skill_selector import SkillSelector
from backend.agent_runtime.unified import AdvancedEvidence, AdvancedRuntimeResult
from backend.apps.api import product_service as product_service_module
from backend.apps.api.product_service import PaperAgentApplication, PaperAgentProcessor
from backend.apps.worker.fake_queue import FakeTaskQueue
from backend.core.domain.blackboard import (
    BlackboardEntry,
    BlackboardEntryKind,
    EvidenceSource,
)
from backend.core.errors import ProjectError
from backend.core.ports.scholarly import ScholarlySearchPage, ScholarlyWork
from backend.infrastructure.fake.adapters import FakeObjectStore
from backend.infrastructure.fake.llm_clients import FakeEmbeddingClient, FakeRerankerClient
from backend.infrastructure.fake.observability import FakeTraceWriter
from backend.infrastructure.postgres.blackboard import (
    ManagedSqlAlchemyBlackboardRepository,
)
from backend.infrastructure.postgres.models import (
    Base,
    ConversationFileModel,
    ConversationModel,
    ConversationSummaryModel,
    DocumentChunkModel,
    DocumentSectionModel,
    FileModel,
    MemorySegmentModel,
    MessageModel,
    ParsedDocumentModel,
    UserModel,
    WorkspaceModel,
)
from backend.memory import (
    ConversationMemoryCoordinator,
    LongTermMemoryService,
    ShortTermMemoryService,
)
from backend.rag.indexing import CURRENT_INDEX_VERSION, CURRENT_SECTION_SCHEMA_VERSION
from backend.skills.loader import SkillManifestLoader, SkillRegistry
from backend.skills.runtime import SkillRuntime
from backend.tool_runtime.runtime import (
    InMemoryDataRefStore,
    InMemoryIdempotencyStore,
    ToolRegistry,
    ToolRuntime,
)
from backend.tool_runtime.scholarly_search_tools import register_scholarly_search_tools

SKILLS_ROOT = Path(__file__).resolve().parents[1] / "backend" / "skills"
REAL_TOOLS = {
    "parse_document",
    "search_document",
    "get_document_section",
    "extract_paper_card",
    "build_comparison_table",
    "build_literature_review",
    "save_artifact",
    "search_crossref",
    "search_semantic_scholar",
    "search_openalex",
    "search_arxiv",
}


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


class ComparisonLLM(RecordingLLM):
    def __init__(self) -> None:
        super().__init__()
        self.generation_count = 0

    async def generate(self, prompt: str, **_kwargs) -> str:
        self.prompt = prompt
        self.generation_count += 1
        if self.generation_count == 1:
            return (
                "Alpha 研究结构化智能体 [E1]，Beta 研究检索增强生成 [E5]。"
                "两篇论文都研究学术智能体，但技术重点不同。"
            )
        return (
            "| 论文 | 主要内容 |\n"
            "|---|---|\n"
            "| alpha.pdf | Alpha 研究结构化智能体 [E1]。 |\n"
            "| beta.pdf | Beta 研究检索增强生成 [E5]。 |\n\n"
            "两篇论文都研究学术智能体，但技术重点不同。"
        )

    async def generate_with_schema(self, prompt: str, **_kwargs) -> str:
        return (
            '{"action":"retrieve","search_query":"主要内容 方法 贡献",'
            '"section_hint":null,"clarification_question":null}'
        )


class MemoryAnswerLLM(RecordingLLM):
    async def generate(self, prompt: str, **_kwargs) -> str:
        self.prompt = prompt
        return "我已根据可追溯的历史原始消息回答该问题。"

    async def generate_with_schema(self, prompt: str, **_kwargs) -> str:
        return (
            '{"action":"answer","search_query":null,'
            '"section_hint":null,"clarification_question":null}'
        )


class AcademicRewriteLLM(RecordingLLM):
    async def generate(self, prompt: str, **_kwargs) -> str:
        self.prompt = prompt
        return (
            "随着企业数字化转型与人工智能技术的深入发展，复杂业务环境中的流程运行管理"
            "正由经验驱动逐步转向数据驱动。事件日志为流程状态感知、偏差识别与资源优化"
            "提供了重要基础。由此，流程监控、诊断和优化能够形成连贯的智能化管理体系。"
        )


def _skill_runtime() -> SkillRuntime:
    registry = SkillRegistry(FakeTraceWriter())
    registry.load_all(
        SkillManifestLoader(
            SKILLS_ROOT,
            registered_tools=REAL_TOOLS,
            available_profiles={"development", "paper_reader_v1"},
        )
    )
    return SkillRuntime(
        SkillSelector(registry, fallback_skill="paper_reader"), registry
    )


class _FakeScholarlyProvider:
    def __init__(self, source: str) -> None:
        self.source = source

    async def search(
        self,
        query: str,
        *,
        limit: int,
        year_from: int | None = None,
        year_to: int | None = None,
    ) -> ScholarlySearchPage:
        del limit, year_from, year_to
        return ScholarlySearchPage(
            source=self.source,
            query=query,
            total=1,
            works=(
                ScholarlyWork(
                    source=self.source,
                    external_id=f"{self.source}-paper",
                    title="Agentic Retrieval Augmented Generation",
                    authors=("Ada Lovelace",),
                    year=2025,
                    doi="10.1000/agentic-rag",
                    url="https://doi.org/10.1000/agentic-rag",
                    citation_count=10,
                ),
            ),
        )


@pytest.mark.asyncio
async def test_topic_paper_search_runs_skill_and_four_tools_without_pdf(
    product_database,
) -> None:
    traces = FakeTraceWriter()
    registry = ToolRegistry()
    register_scholarly_search_tools(
        registry,
        crossref=_FakeScholarlyProvider("crossref"),
        semantic_scholar=_FakeScholarlyProvider("semantic_scholar"),
        openalex=_FakeScholarlyProvider("openalex"),
        arxiv=_FakeScholarlyProvider("arxiv"),
    )
    processor = PaperAgentProcessor(
        product_database,
        FakeObjectStore(),
        FakeEmbeddingClient(),
        FakeRerankerClient(),
        RecordingLLM(),
        skill_runtime=_skill_runtime(),
        tool_runtime=ToolRuntime(
            registry,
            idempotency_store=InMemoryIdempotencyStore(),
            data_ref_store=InMemoryDataRefStore(),
            trace_writer=traces,
        ),
    )

    result = await processor.answer(
        {
            "_task_id": "paper-discovery-task",
            "conversation_id": "conversation-1",
            "question": "帮我找几篇关于 Agentic RAG 的论文",
            "file_ids": [],
        }
    )

    assert result["status"] == "completed"
    assert result["answer"].count("Agentic Retrieval Augmented Generation") == 1
    assert "crossref, semantic_scholar, openalex, arxiv" not in result["answer"]
    assert all(source in result["answer"] for source in ("crossref", "semantic_scholar", "openalex", "arxiv"))
    assert len([trace for trace in traces.traces if trace["span_name"] == "tool.invoke"]) == 4
    with product_database() as session:
        message = session.get(MessageModel, result["message_id"])
        assert message is not None
        assert message.metadata_json["rag"]["decision"] == "scholarly_search"
        assert message.metadata_json["evidence"] == []


@pytest.mark.asyncio
async def test_multi_agent_result_uses_normal_message_evidence_and_memory_path(
    product_database,
) -> None:
    queue = FakeTaskQueue()
    llm = RecordingLLM()
    processor = PaperAgentProcessor(
        product_database,
        FakeObjectStore(),
        FakeEmbeddingClient(),
        FakeRerankerClient(),
        llm,
        memory_task_queue=queue,
    )
    result = AdvancedRuntimeResult(
        answer="论文 A 与论文 B 的结果均为 92% [E1][E2]",
        citation_ids=["E1", "E2"],
        evidence=[
            AdvancedEvidence(
                id="E1",
                file_id="paper-a",
                page=1,
                section=["Results"],
                quote="Paper A reports 92%.",
                bbox=[0.1, 0.1, 0.8, 0.2],
                source_evidence_id="chunk-a",
            ),
            AdvancedEvidence(
                id="E2",
                file_id="paper-b",
                page=2,
                section=["Results"],
                quote="Paper B reports 92%.",
                bbox=[0.1, 0.2, 0.8, 0.3],
                source_evidence_id="chunk-b",
            ),
        ],
        agent_roles=[
            "coordinator",
            "paper_reader",
            "evidence",
            "critic",
            "writer",
            "verifier",
        ],
        subagent_run_ids=["reader:paper-a", "reader:paper-b"],
        blackboard_entry_ids=["evidence", "writer", "verifier"],
        revision_rounds=1,
    )

    saved = await processor._save_advanced_runtime_answer(  # noqa: SLF001
        "conversation-1",
        "multi-task",
        "比较两篇论文",
        "multi_agent",
        result,
        {
            "source_message_ids": [],
            "short_term_memory_used": False,
            "long_term_memory_used": False,
            "memory_segment_ids": [],
            "memory_conversation_ids": [],
        },
    )

    assert saved["status"] == "completed"
    assert llm.prompt == ""
    with product_database() as session:
        message = session.get(MessageModel, saved["message_id"])
        assert message is not None
        assert message.metadata_json["rag"]["runtime_mode"] == "multi_agent"
        assert message.metadata_json["rag"]["revision_rounds"] == 1
        assert [item["id"] for item in message.metadata_json["evidence"]] == [
            "E1",
            "E2",
        ]
    assert any(
        task.task_type == "memory_summary" for task in queue.tasks.values()
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
async def test_answer_recalls_short_term_memory_and_schedules_summary(
    product_database,
) -> None:
    with product_database() as session:
        session.add(
            MessageModel(
                id="old-memory-message",
                workspace_id="local-workspace",
                conversation_id="conversation-1",
                role="user",
                type="text",
                content="memorytoken42 对应的是早期讨论的评测约束。",
                metadata_json={},
            )
        )
        for index in range(30):
            session.add(
                MessageModel(
                    id=f"filler-{index}",
                    workspace_id="local-workspace",
                    conversation_id="conversation-1",
                    role="assistant" if index % 2 else "user",
                    type="text",
                    content=f"无关的近期占位消息 {index}",
                    metadata_json={},
                )
            )
        session.commit()
    embeddings = FakeEmbeddingClient()
    short_memory = ShortTermMemoryService(
        product_database,
        embeddings,
    )
    long_memory = LongTermMemoryService(product_database, embeddings)
    coordinator = ConversationMemoryCoordinator(short_memory, long_memory)
    await coordinator.summarize("local-workspace", "conversation-1")
    queue = FakeTaskQueue()
    llm = MemoryAnswerLLM()
    processor = PaperAgentProcessor(
        product_database,
        FakeObjectStore(),
        embeddings,
        FakeRerankerClient(),
        llm,
        short_term_memory=short_memory,
        long_term_memory=long_memory,
        memory_task_queue=queue,
    )

    result = await processor.answer(
        {
            "_task_id": "memory-answer-task",
            "conversation_id": "conversation-1",
            "question": "memorytoken42 指的是什么？",
            "file_ids": [],
        }
    )

    assert result["status"] == "completed"
    assert "memorytoken42 对应的是早期讨论" in llm.prompt
    assert any(
        task.task_type == "memory_summary" for task in queue.tasks.values()
    )
    with product_database() as session:
        answer = session.scalars(
            select(MessageModel)
            .where(MessageModel.role == "assistant")
            .order_by(MessageModel.created_at.desc(), MessageModel.id.desc())
        ).first()
        assert answer is not None
        rag = answer.metadata_json["rag"]
        assert rag["short_term_memory_used"] is True
        assert "old-memory-message" in rag["history_source_message_ids"]


@pytest.mark.asyncio
async def test_explicit_historical_question_recalls_another_conversation(
    product_database,
) -> None:
    with product_database() as session:
        session.add(
            ConversationModel(
                id="conversation-2",
                workspace_id="local-workspace",
                user_id="local-user",
                title="Earlier research",
            )
        )
        session.add(
            MessageModel(
                id="cross-conversation-message",
                workspace_id="local-workspace",
                conversation_id="conversation-2",
                role="user",
                type="text",
                content="crosssession77 是以前会话确定的消融实验代号。",
                metadata_json={},
            )
        )
        session.commit()
    embeddings = FakeEmbeddingClient()
    short_memory = ShortTermMemoryService(product_database, embeddings)
    long_memory = LongTermMemoryService(product_database, embeddings)
    coordinator = ConversationMemoryCoordinator(short_memory, long_memory)
    await coordinator.summarize("local-workspace", "conversation-2")
    llm = MemoryAnswerLLM()
    processor = PaperAgentProcessor(
        product_database,
        FakeObjectStore(),
        embeddings,
        FakeRerankerClient(),
        llm,
        short_term_memory=short_memory,
        long_term_memory=long_memory,
    )

    result = await processor.answer(
        {
            "_task_id": "long-memory-task",
            "conversation_id": "conversation-1",
            "question": "以前其他会话中说的 crosssession77 是什么？",
            "file_ids": [],
        }
    )

    assert result["status"] == "completed"
    assert "crosssession77 是以前会话确定" in llm.prompt
    with product_database() as session:
        answer = session.scalars(
            select(MessageModel)
            .where(
                MessageModel.conversation_id == "conversation-1",
                MessageModel.role == "assistant",
            )
            .order_by(MessageModel.created_at.desc(), MessageModel.id.desc())
        ).first()
        assert answer is not None
        rag = answer.metadata_json["rag"]
        assert rag["long_term_memory_used"] is True
        assert rag["memory_conversation_ids"] == ["conversation-2"]
        assert "cross-conversation-message" in rag["history_source_message_ids"]


@pytest.mark.asyncio
async def test_memory_summary_coordinator_persists_both_memory_levels(
    product_database,
) -> None:
    with product_database() as session:
        for index in range(13):
            session.add(
                MessageModel(
                    id=f"summary-source-{index}",
                    workspace_id="local-workspace",
                    conversation_id="conversation-1",
                    role="user" if index % 2 == 0 else "assistant",
                    type="text",
                    content=f"摘要来源消息 {index}",
                    metadata_json={},
                )
            )
        session.commit()
    embeddings = FakeEmbeddingClient()
    coordinator = ConversationMemoryCoordinator(
            ShortTermMemoryService(
                product_database,
                embeddings,
            ),
        LongTermMemoryService(product_database, embeddings),
    )

    result = await coordinator.summarize(
        "local-workspace",
        "conversation-1",
    )

    assert result["status"] == "completed"
    assert result["short_term_segment_id"]
    assert result["long_term_summary_id"] == "conversation-1"
    with product_database() as session:
        assert session.query(MemorySegmentModel).count() == 1
        assert session.query(ConversationSummaryModel).count() == 1


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
async def test_short_follow_up_ending_with_ne_uses_the_immediately_previous_exchange(
    product_database,
) -> None:
    with product_database() as session:
        _add_debug_index(session)
        session.add_all(
            [
                MessageModel(
                    id="results-user",
                    workspace_id="local-workspace",
                    conversation_id="conversation-1",
                    role="user",
                    type="text",
                    content="这篇论文采用了什么方法？",
                    metadata_json={},
                ),
                MessageModel(
                    id="results-assistant",
                    workspace_id="local-workspace",
                    conversation_id="conversation-1",
                    role="assistant",
                    type="text",
                    content="论文采用结构化 Agent runtime。",
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
            "_task_id": "short-ne-follow-up-task",
            "conversation_id": "conversation-1",
            "question": "准确率呢？",
            "file_ids": ["file-debug"],
        }
    )

    assert result["status"] == "completed"
    assert "这篇论文采用了什么方法" in llm.prompt
    assert "结构化 Agent runtime" in llm.prompt
    with product_database() as session:
        answer = session.scalars(
            select(MessageModel)
            .where(MessageModel.role == "assistant")
            .order_by(MessageModel.created_at.desc(), MessageModel.id.desc())
        ).first()
        assert answer is not None
        rag = answer.metadata_json["rag"]
        assert rag["history_used"] is True
        assert "这篇论文采用了什么方法" in rag["query"]


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
async def test_submit_message_ignores_a_stale_deleted_file_and_keeps_the_follow_up(
    product_database,
) -> None:
    deleted_at = datetime.now(UTC)
    with product_database() as session:
        session.add(
            FileModel(
                id="stale-file",
                workspace_id="local-workspace",
                filename="stale.pdf",
                content_type="application/pdf",
                size_bytes=1,
                storage_path="uploads/stale.pdf",
                checksum="e" * 64,
                is_deleted=True,
                reference_count=0,
                deleted_at=deleted_at,
                metadata_json={"parse_status": "deleted"},
            )
        )
        session.add(
            ConversationFileModel(
                id="stale-link",
                workspace_id="local-workspace",
                conversation_id="conversation-1",
                file_id="stale-file",
            )
        )
        session.commit()
    queue = FakeTaskQueue()
    application = PaperAgentApplication(
        product_database,
        FakeObjectStore(),
        queue,
    )

    result = await application.submit_message(
        "conversation-1",
        "那实验结果呢？",
        ["stale-file"],
    )

    with product_database() as session:
        saved = session.get(MessageModel, result["message"]["id"])
        assert saved is not None
        assert saved.content == "那实验结果呢？"
    assert queue.tasks[result["task_id"]].payload["file_ids"] == []


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

    blackboard = ManagedSqlAlchemyBlackboardRepository(product_database)
    for entry in (
        BlackboardEntry(
            entry_id="reader:file-delete",
            workspace_id="local-workspace",
            task_id="delete-task",
            kind=BlackboardEntryKind.PAPER_CARD,
            producer_role="paper_reader",
            confidence=1,
            payload={"paper_id": "file-delete"},
            source=EvidenceSource(file_id="file-delete"),
        ),
        BlackboardEntry(
            entry_id="writer",
            workspace_id="local-workspace",
            task_id="delete-task",
            kind=BlackboardEntryKind.DRAFT_SECTION,
            producer_role="writer",
            confidence=1,
            payload={"answer": "derived"},
            source=EvidenceSource(inferred=True),
        ),
    ):
        await blackboard.append(entry, expected_version=0)
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
    assert (
        await blackboard.list_active("local-workspace", "delete-task")
        == []
    )


@pytest.mark.asyncio
async def test_delete_conversation_preserves_a_file_shared_by_an_active_conversation(
    product_database,
) -> None:
    store = FakeObjectStore()
    data = _paper_pdf()
    object_key = await store.upload("uploads/shared.pdf", data, "application/pdf")
    with product_database() as session:
        session.add(
            ConversationModel(
                id="conversation-2",
                workspace_id="local-workspace",
                user_id="local-user",
                title="Second conversation",
            )
        )
        session.add(
            FileModel(
                id="shared-file",
                workspace_id="local-workspace",
                filename="shared.pdf",
                content_type="application/pdf",
                size_bytes=len(data),
                storage_path=object_key,
                checksum="f" * 64,
                reference_count=2,
                metadata_json={"parse_status": "parsed"},
            )
        )
        session.add_all(
            [
                ConversationFileModel(
                    id="shared-link-1",
                    workspace_id="local-workspace",
                    conversation_id="conversation-1",
                    file_id="shared-file",
                ),
                ConversationFileModel(
                    id="shared-link-2",
                    workspace_id="local-workspace",
                    conversation_id="conversation-2",
                    file_id="shared-file",
                ),
            ]
        )
        session.commit()
    application = PaperAgentApplication(product_database, store, FakeTaskQueue())

    result = await application.delete_conversation("conversation-1")

    assert result["deleted_file_count"] == 0
    assert await store.exists(object_key)
    remaining = await application.get_conversation("conversation-2")
    assert [item["id"] for item in remaining["files"]] == ["shared-file"]
    with product_database() as session:
        file_model = session.get(FileModel, "shared-file")
        assert file_model is not None
        assert file_model.is_deleted is False
        assert file_model.deleted_at is None
        assert file_model.reference_count == 1


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


def _add_comparison_indexes(session) -> None:
    for paper_index, (file_id, filename, topic) in enumerate(
        (
            ("file-alpha", "alpha.pdf", "结构化智能体"),
            ("file-beta", "beta.pdf", "检索增强生成"),
        ),
        1,
    ):
        checksum = str(paper_index) * 64
        document_id = f"document-{paper_index}"
        section_id = f"section-{paper_index}"
        session.add(
            FileModel(
                id=file_id,
                workspace_id="local-workspace",
                filename=filename,
                content_type="application/pdf",
                size_bytes=100,
                storage_path=f"uploads/{filename}",
                checksum=checksum,
                metadata_json={"parse_status": "parsed"},
            )
        )
        session.add(
            ConversationFileModel(
                id=f"link-{paper_index}",
                workspace_id="local-workspace",
                conversation_id="conversation-1",
                file_id=file_id,
            )
        )
        session.add(
            ParsedDocumentModel(
                id=document_id,
                workspace_id="local-workspace",
                file_id=file_id,
                checksum=checksum,
                parser_name="fixture",
                parser_version="1",
                page_count=1,
                quality_score=99,
                metadata_json={
                    "index_version": CURRENT_INDEX_VERSION,
                    "section_schema_version": CURRENT_SECTION_SCHEMA_VERSION,
                },
            )
        )
        session.add(
            DocumentSectionModel(
                id=section_id,
                workspace_id="local-workspace",
                file_id=file_id,
                document_id=document_id,
                section_id=section_id,
                number="1",
                title="Introduction",
                normalized_title="introduction",
                level=1,
                parent_section_id=None,
                section_path=["1 Introduction"],
                ordinal=1,
                page_start=1,
                page_end=1,
                heading_block_id=f"heading-{paper_index}",
                block_ids=[f"heading-{paper_index}", f"body-{paper_index}"],
                descendant_block_ids=[
                    f"heading-{paper_index}",
                    f"body-{paper_index}",
                ],
            )
        )
        chunk_count = 12 if file_id == "file-alpha" else 1
        for chunk_index in range(chunk_count):
            session.add(
                DocumentChunkModel(
                    id=f"chunk-{paper_index}-{chunk_index}",
                    workspace_id="local-workspace",
                    file_id=file_id,
                    document_id=document_id,
                    parent_chunk_id=None,
                    level="child",
                    section_id=section_id,
                    section_title="Introduction",
                    section_path=["1 Introduction"],
                    chunk_index_in_section=chunk_index,
                    text=f"论文主要内容、方法和贡献聚焦于{topic}。",
                    page_start=1,
                    page_end=1,
                    bbox_json=[0, 0, 100, 100],
                    source_block_ids=[f"body-{paper_index}"],
                    embedding=[0.2] * 1024,
                    embedding_model="multilingual-hash-v1",
                    searchable_text=f"主要内容 方法 贡献 {topic}",
                )
            )


@pytest.mark.asyncio
async def test_multi_document_comparison_balances_evidence_and_uses_file_names(
    product_database,
) -> None:
    with product_database() as session:
        _add_comparison_indexes(session)
        session.commit()
    llm = ComparisonLLM()
    processor = PaperAgentProcessor(
        product_database,
        FakeObjectStore(),
        FakeEmbeddingClient(),
        FakeRerankerClient(),
        llm,
        skill_runtime=_skill_runtime(),
    )

    result = await processor.answer(
        {
            "_task_id": "comparison-task",
            "conversation_id": "conversation-1",
            "question": "对比一下这两篇文章的主要内容",
            "file_ids": ["file-alpha", "file-beta"],
        }
    )

    assert result["status"] == "completed"
    assert llm.generation_count == 2
    assert "上一次回答的结构不符合" in llm.prompt
    assert "论文 alpha.pdf" in llm.prompt
    assert "论文 beta.pdf" in llm.prompt
    with product_database() as session:
        answer = session.scalar(
            select(MessageModel).where(MessageModel.role == "assistant")
        )
        assert answer is not None
        assert {
            evidence["file_id"] for evidence in answer.metadata_json["evidence"]
        } == {"file-alpha", "file-beta"}
        assert (
            answer.metadata_json["rag"]["retrieval_mode"]
            == "comparison_balanced_rag"
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
async def test_inline_academic_rewrite_does_not_require_uploaded_paper(
    product_database,
) -> None:
    llm = AcademicRewriteLLM()
    processor = PaperAgentProcessor(
        product_database,
        FakeObjectStore(),
        FakeEmbeddingClient(),
        FakeRerankerClient(),
        llm,
        skill_runtime=_skill_runtime(),
    )
    request = (
        "随着企业数字化转型和人工智能技术的深入发展，业务流程运行管理正在由经验驱动、"
        "人工监督和事后分析，逐步转向数据驱动、实时感知和智能决策。复杂运营情境会受到"
        "客户需求变化、资源状态波动、组织协同关系和异常事件扰动等多种因素影响。\n\n"
        "请把‘复杂业务环境下’这一背景自然、连贯地融入上面的学术段落并完成润色。"
    )

    result = await processor.answer(
        {
            "_task_id": "rewrite-inline",
            "conversation_id": "conversation-1",
            "question": request,
            "message_id": "current-rewrite-message",
            "file_ids": [],
        }
    )

    assert result["status"] == "completed"
    assert "上传" not in result["answer"]
    assert "<SOURCE_TEXT>" in llm.prompt
    with product_database() as session:
        answer = session.scalar(select(MessageModel).where(MessageModel.role == "assistant"))
        assert answer.metadata_json["rag"]["decision"] == "academic_rewrite"
        assert answer.metadata_json["rag"]["source_mode"] == "inline_text"


@pytest.mark.asyncio
async def test_new_rewrite_request_replaces_pending_document_task(
    product_database,
) -> None:
    llm = AcademicRewriteLLM()
    processor = PaperAgentProcessor(
        product_database,
        FakeObjectStore(),
        FakeEmbeddingClient(),
        FakeRerankerClient(),
        llm,
        skill_runtime=_skill_runtime(),
    )
    new_request = (
        "请润色下面这段学术文字：复杂业务环境中的流程运行受到需求变化、资源波动、"
        "组织协同和异常事件的共同影响，因此需要形成面向实时监控、风险诊断和动态优化"
        "的一体化方法体系，并保证段落表达自然连贯且不增加新的研究事实。"
    )

    result = await processor.answer(
        {
            "_task_id": "old-root-task",
            "conversation_id": "conversation-1",
            "question": "请总结这篇论文的实验章节",
            "clarification_answer": new_request,
            "clarification_round": 1,
            "message_id": "new-task-message",
            "file_ids": [],
        }
    )

    assert result["status"] == "completed"
    assert "请上传或选择" not in result["answer"]


@pytest.mark.asyncio
async def test_rewrite_follow_up_rereads_exact_historical_message(
    product_database,
) -> None:
    source = (
        "业务流程运行受到客户需求变化、资源状态波动、组织协同关系和异常事件扰动的"
        "共同影响，呈现出高度动态性、情境耦合性和目标冲突性，因此传统事后统计方法"
        "难以满足复杂业务环境中的实时监控、风险诊断和动态优化需求。"
    )
    with product_database() as session:
        session.add(
            MessageModel(
                id="historical-rewrite-source",
                workspace_id="local-workspace",
                conversation_id="conversation-1",
                role="user",
                type="text",
                content=source,
                metadata_json={},
            )
        )
        session.commit()
    llm = AcademicRewriteLLM()
    processor = PaperAgentProcessor(
        product_database,
        FakeObjectStore(),
        FakeEmbeddingClient(),
        FakeRerankerClient(),
        llm,
        skill_runtime=_skill_runtime(),
    )

    result = await processor.answer(
        {
            "_task_id": "rewrite-history",
            "conversation_id": "conversation-1",
            "question": "继续润色之前那段，让逻辑更连贯。",
            "message_id": "current-follow-up",
            "file_ids": [],
        }
    )

    assert result["status"] == "completed"
    assert source in llm.prompt
    with product_database() as session:
        answer = session.scalar(
            select(MessageModel).where(MessageModel.role == "assistant")
        )
        material_ref = answer.metadata_json["rag"]["material_refs"][0]
        assert material_ref["message_id"] == "historical-rewrite-source"
        assert material_ref["sha256"] == hashlib.sha256(source.encode("utf-8")).hexdigest()


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
