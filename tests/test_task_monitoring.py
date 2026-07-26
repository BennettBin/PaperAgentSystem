import json
from io import BytesIO
from pathlib import Path

import fitz
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.agent_runtime.skill_selector import SkillSelector
from backend.apps.api.product_service import PaperAgentApplication, PaperAgentProcessor
from backend.apps.worker.fake_queue import FakeTaskQueue
from backend.infrastructure.fake.adapters import FakeObjectStore
from backend.infrastructure.fake.llm_clients import FakeEmbeddingClient, FakeRerankerClient
from backend.infrastructure.fake.observability import FakeTraceWriter
from backend.infrastructure.postgres.models import (
    Base,
    ConversationFileModel,
    ConversationModel,
    FileModel,
    QueueJobModel,
    UserModel,
    WorkspaceModel,
)
from backend.infrastructure.sse.service import TaskEventStore
from backend.observability.task_audit_log import JsonlTaskAuditLogWriter
from backend.skills.loader import SkillManifestLoader, SkillRegistry
from backend.skills.runtime import SkillRuntime

SKILLS_ROOT = Path(__file__).resolve().parents[1] / "backend" / "skills"


def _skill_runtime() -> tuple[SkillRuntime, FakeTraceWriter]:
    traces = FakeTraceWriter()
    registry = SkillRegistry(traces)
    registry.load_all(
        SkillManifestLoader(
            SKILLS_ROOT,
            registered_tools={
                "parse_document", "get_document_section", "search_document",
                "build_comparison_table",
                "save_artifact",
                "build_literature_review", "extract_paper_card",
                "search_crossref", "search_semantic_scholar",
                "search_openalex", "search_arxiv",
            },
            available_profiles={"development", "paper_reader_v1"},
        )
    )
    return SkillRuntime(SkillSelector(registry, fallback_skill="paper_reader"), registry), traces


class _MonitoringLLM:
    async def generate_with_schema(self, _prompt: str, **_kwargs) -> str:
        return (
            '{"action":"retrieve","search_query":"PaperBench dataset",'
            '"section_hint":null,"clarification_question":null}'
        )

    async def generate(self, _prompt: str, **_kwargs) -> str:
        return "论文使用 PaperBench 数据集进行验证 [E1]。"


def _paper_pdf() -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((50, 60), "Methods", fontsize=16)
    page.insert_text((50, 100), "The PaperBench dataset is used for evaluation.")
    stream = BytesIO()
    document.save(stream)
    document.close()
    return stream.getvalue()


@pytest.fixture
def product_database(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'monitor.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as session:
        session.add(UserModel(id="local-user", email="local@example.test", name="Local"))
        session.add(
            WorkspaceModel(
                id="local-workspace", user_id="local-user", name="Local workspace"
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


def test_jsonl_task_audit_log_records_safe_file_access(tmp_path) -> None:
    writer = JsonlTaskAuditLogWriter(tmp_path)

    writer.append(
        "task-1",
        "object.download",
        component="object_store",
        status="completed",
        details={
            "file_id": "file-1",
            "storage_path": "uploads/paper.pdf",
            "question": "不应写入日志的用户问题",
        },
    )

    log_path = tmp_path / "task-1.jsonl"
    record = json.loads(log_path.read_text(encoding="utf-8"))
    assert record["task_id"] == "task-1"
    assert record["details"] == {
        "file_id": "file-1",
        "storage_path": "uploads/paper.pdf",
    }
    assert "不应写入日志" not in log_path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_task_monitor_returns_persisted_progress_and_log_address(
    product_database,
) -> None:
    with product_database() as session:
        session.add(
            QueueJobModel(
                id="task-monitor-1",
                task_type="main_agent",
                queue_name="main_agent",
                payload={"conversation_id": "conversation-1"},
                idempotency_key="task-monitor-1",
                status="running",
                priority=0,
                attempts=1,
                max_retries=3,
                result=None,
                error=None,
            )
        )
        session.commit()
    events = TaskEventStore(product_database)
    events.append(
        "task-monitor-1",
        "step_started",
        "小模型进行问题判断",
        {"stage": "intent_routing"},
    )
    events.append(
        "task-monitor-1",
        "skill_selected",
        "调用 paper_qa Skill",
        {"skill_name": "paper_qa", "file_ids": ["file-1"]},
    )
    application = PaperAgentApplication(
        product_database,
        FakeObjectStore(),
        FakeTaskQueue(),
    )

    monitor = await application.get_task_monitor("task-monitor-1")

    assert monitor["status"] == "running"
    assert monitor["events"][0]["title"] == "小模型进行问题判断"
    assert monitor["events"][0]["sequence"] == 1
    assert monitor["events"][1]["type"] == "step_started"
    assert monitor["events"][1]["title"] == "执行论文问答 RAG 流程"
    assert monitor["events"][1]["data"] == {
        "stage": "paper_qa_rag",
        "file_ids": ["file-1"],
    }
    assert monitor["log_path"] == "runtime/logs/agent/task-monitor-1.jsonl"


@pytest.mark.asyncio
async def test_answer_pipeline_emits_public_stages_and_detailed_file_log(
    product_database, tmp_path
) -> None:
    store = FakeObjectStore()
    pdf = _paper_pdf()
    storage_path = await store.upload("uploads/monitor.pdf", pdf, "application/pdf")
    with product_database() as session:
        session.add(
            FileModel(
                id="monitor-file",
                workspace_id="local-workspace",
                filename="monitor.pdf",
                content_type="application/pdf",
                size_bytes=len(pdf),
                storage_path=storage_path,
                checksum="c" * 64,
                metadata_json={"parse_status": "queued"},
            )
        )
        session.add(
            ConversationFileModel(
                id="monitor-link",
                workspace_id="local-workspace",
                conversation_id="conversation-1",
                file_id="monitor-file",
            )
        )
        session.commit()
    events = TaskEventStore(product_database)
    skill_runtime, skill_traces = _skill_runtime()
    processor = PaperAgentProcessor(
        product_database,
        store,
        FakeEmbeddingClient(),
        FakeRerankerClient(),
        _MonitoringLLM(),
        events,
        audit_log_writer=JsonlTaskAuditLogWriter(tmp_path / "agent_logs"),
        skill_runtime=skill_runtime,
    )

    await processor.answer(
        {
            "_task_id": "answer-monitor-task",
            "conversation_id": "conversation-1",
            "question": "这篇文章使用什么数据集？",
            "file_ids": ["monitor-file"],
        }
    )

    titles = [event.title for event in events.after("answer-monitor-task", 0)]
    assert "小模型进行问题判断" in titles
    assert "执行论文问答 RAG 流程" in titles
    assert "调用 paper_qa Skill" not in titles
    assert "调用 paper_reader Skill" in titles
    assert "调用 document_parser Skill" in titles
    assert [item["span_name"] for item in skill_traces.traces].count("skill.activate") == 2
    assert [item["span_name"] for item in skill_traces.traces].count("skill.complete") == 2
    rag_event = next(
        event
        for event in events.after("answer-monitor-task", 0)
        if event.title == "执行论文问答 RAG 流程"
    )
    assert rag_event.event_type == "step_started"
    assert "大模型进行回答生成" in titles
    assert "Verifier 进行回答检验" in titles
    log_text = (tmp_path / "agent_logs" / "answer-monitor-task.jsonl").read_text(
        encoding="utf-8"
    )
    assert "uploads/monitor.pdf" in log_text
    assert "这篇文章使用什么数据集" not in log_text
