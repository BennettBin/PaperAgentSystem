from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.apps.api.product_service import PaperAgentApplication
from backend.apps.worker.fake_queue import FakeTaskQueue
from backend.core.ports.storage import TaskQueue
from backend.infrastructure.fake.adapters import FakeObjectStore
from backend.infrastructure.fake.llm_clients import FakeEmbeddingClient, FakeRerankerClient
from backend.infrastructure.postgres.models import (
    Base,
    ConversationModel,
    UserModel,
    WorkspaceModel,
)
from backend.rag.retrieval import HybridRetriever

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class RecordingQueue(TaskQueue):
    cancelled: list[str] = field(default_factory=list)

    async def enqueue(
        self, task_type: str, payload: dict, idempotency_key: str, priority: int = 0
    ) -> str:
        del task_type, payload, idempotency_key, priority
        return "unused"

    async def get_status(self, task_id: str) -> str:
        del task_id
        return "queued"

    async def get_result(self, task_id: str) -> dict | None:
        del task_id
        return None

    async def cancel(self, task_id: str) -> bool:
        self.cancelled.append(task_id)
        return True

    async def resume(self, task_id: str, payload: dict) -> bool:
        del task_id, payload
        return False


@pytest.fixture
def product_database(tmp_path: Path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'product.db').as_posix()}")
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


def test_retired_document_writer_modules_are_physically_deleted() -> None:
    retired = (
        "backend/document_processing/pipeline.py",
        "backend/document_processing/pdf_parser.py",
        "backend/document_processing/ocr.py",
        "backend/document_processing/rollout.py",
        "backend/rag/indexing.py",
        "backend/apps/worker/document_rollout.py",
        "backend/apps/worker/document_rollout_admin.py",
        "evaluation/pdf_parsing_baseline.py",
        "evaluation/pdf_rollout_drill.py",
    )

    assert [path for path in retired if (ROOT / path).exists()] == []


def test_production_composition_contains_no_v1_or_shadow_writer_tokens() -> None:
    production_files = (
        "backend/apps/api/dependencies.py",
        "backend/apps/api/product_service.py",
        "backend/apps/worker/runtime.py",
        "backend/document_processing/adaptive_pipeline.py",
        "backend/tool_runtime/document_tools.py",
    )
    forbidden = (
        "BasicPDFPipeline",
        "DocumentPipelineSnapshot",
        "DocumentIndexer(",
        "shadow_diagnostics",
        "shadow_error",
        "rollout_snapshot",
    )

    violations = {
        path: [token for token in forbidden if token in (ROOT / path).read_text(encoding="utf-8")]
        for path in production_files
    }
    assert {path: tokens for path, tokens in violations.items() if tokens} == {}


@pytest.mark.asyncio
async def test_new_upload_task_contains_no_legacy_pipeline_snapshot(product_database) -> None:
    queue = FakeTaskQueue()
    application = PaperAgentApplication(product_database, FakeObjectStore(), queue)

    uploaded = await application.upload_file(
        "conversation-1",
        "v2-only.pdf",
        "application/pdf",
        b"%PDF-1.7\nPDF-V12 controlled sample",
    )

    payload = queue.tasks[uploaded["task_id"]].payload
    assert payload == {"file_id": uploaded["id"]}


def test_twelve_legacy_snapshot_jobs_are_classified_without_payload_rewrite(
    tmp_path: Path,
) -> None:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from backend.apps.worker.document_v2_migration import LegacyDocumentTaskDrainService
    from backend.infrastructure.postgres.models import Base, QueueJobModel

    engine = create_engine(f"sqlite:///{(tmp_path / 'v12-drain.db').as_posix()}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    original_payloads: dict[str, dict[str, object]] = {}
    with sessions() as session:
        for index in range(12):
            job_id = f"legacy-{index:02d}"
            payload: dict[str, object] = {
                "file_id": f"file-{index:02d}",
                "document_pipeline_snapshot": {
                    "v2_enabled": index % 2 == 0,
                    "shadow_mode": index % 3 == 0,
                    "rollout_percentage": 100 if index % 2 == 0 else 0,
                    "policy_revision": "retired-v1-v2-rollout",
                },
            }
            original_payloads[job_id] = payload.copy()
            session.add(
                QueueJobModel(
                    id=job_id,
                    task_type="document_parse",
                    queue_name="document_parse",
                    payload=payload,
                    idempotency_key=f"legacy:{index}",
                    status="queued" if index < 8 else "running",
                    priority=0,
                    max_retries=3,
                )
            )
        session.commit()

    plan = LegacyDocumentTaskDrainService(sessions).inspect(intake_frozen=True)

    assert len(plan.queued_legacy_ids) == 8
    assert len(plan.running_legacy_ids) == 4
    assert plan.safe_for_v2_only_deploy is False
    with sessions() as session:
        stored = {
            job.id: job.payload
            for job in session.query(QueueJobModel).order_by(QueueJobModel.id).all()
        }
    assert stored == original_payloads


@pytest.mark.asyncio
async def test_legacy_drain_cancels_only_queued_and_never_running(tmp_path: Path) -> None:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from backend.apps.worker.document_v2_migration import LegacyDocumentTaskDrainService
    from backend.infrastructure.postgres.models import Base, QueueJobModel

    engine = create_engine(f"sqlite:///{(tmp_path / 'v12-cancel.db').as_posix()}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    with sessions() as session:
        for index, status in enumerate(("queued", "queued", "running")):
            session.add(
                QueueJobModel(
                    id=f"legacy-{status}-{index}",
                    task_type="document_parse",
                    queue_name="document_parse",
                    payload={
                        "file_id": f"file-{index}",
                        "document_pipeline_snapshot": {"retired": True},
                    },
                    idempotency_key=f"legacy-cancel:{index}",
                    status=status,
                    priority=0,
                    max_retries=3,
                )
            )
        session.commit()
    queue = RecordingQueue()

    result = await LegacyDocumentTaskDrainService(sessions).cancel_queued_legacy(
        queue, intake_frozen=True
    )

    assert result.cancelled_ids == ("legacy-queued-0", "legacy-queued-1")
    assert result.running_legacy_ids == ("legacy-running-2",)
    assert queue.cancelled == ["legacy-queued-0", "legacy-queued-1"]


@pytest.mark.asyncio
async def test_existing_v1_chunks_remain_read_only_until_reparse(product_database) -> None:
    from backend.infrastructure.postgres.models import DocumentChunkModel, ParsedDocumentModel

    with product_database() as session:
        session.add(
            ParsedDocumentModel(
                id="legacy-readable-document",
                workspace_id="local-workspace",
                file_id="legacy-readable-file",
                checksum="a" * 64,
                parser_name="pymupdf-v1",
                parser_version="1.0",
                page_count=1,
                quality_score=80,
                metadata_json={"index_version": 4},
            )
        )
        session.add(
            DocumentChunkModel(
                id="legacy-readable-chunk",
                workspace_id="local-workspace",
                file_id="legacy-readable-file",
                document_id="legacy-readable-document",
                parent_chunk_id=None,
                level="child",
                section_id="legacy-section",
                section_number="1",
                section_title="Legacy Results",
                section_path=["Legacy Results"],
                chunk_index_in_section=0,
                text="Legacy calibration evidence remains searchable.",
                page_start=1,
                page_end=1,
                bbox_json=[0, 0, 100, 100],
                source_block_ids=["legacy-block"],
                evidence_spans=[],
                element_types=[],
                content_kind="body",
                contains_inferred_content=False,
                embedding=[0.0] * 1024,
                embedding_model="legacy",
                searchable_text="Legacy Results\nLegacy calibration evidence remains searchable.",
            )
        )
        session.commit()

    hits = await HybridRetriever(
        product_database, FakeEmbeddingClient(), FakeRerankerClient()
    ).search(
        "legacy calibration",
        workspace_id="local-workspace",
        file_ids={"legacy-readable-file"},
    )

    assert hits and hits[0].chunk_id == "legacy-readable-chunk"
    with product_database() as session:
        stored = session.get(ParsedDocumentModel, "legacy-readable-document")
        assert stored is not None and stored.parser_name == "pymupdf-v1"
