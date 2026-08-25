from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.apps.api.product_service import PaperAgentApplication, PaperAgentProcessor
from backend.apps.worker.fake_queue import FakeTaskQueue
from backend.core.errors import ProjectError
from backend.document_processing.adaptive_pipeline import (
    AdaptiveDocumentPipeline,
    ProductionDocumentPipeline,
)
from backend.document_processing.docling_adapter import (
    DoclingBoundingBox,
    DoclingItemCandidate,
    DoclingLayoutAdapter,
)
from backend.document_processing.office_adapter import (
    DoclingOfficeAdapter,
    OfficeBackendResult,
)
from backend.document_processing.paddleocr_vl_adapter import PaddleOCRVLAdapter
from backend.document_processing.pymupdf_adapter import PyMuPDFV2Adapter
from backend.infrastructure.fake.adapters import FakeObjectStore
from backend.infrastructure.fake.llm_clients import FakeEmbeddingClient, FakeRerankerClient
from backend.infrastructure.postgres.models import (
    Base,
    ConversationModel,
    FileModel,
    ParsedDocumentModel,
    UserModel,
    WorkspaceModel,
)
from evaluation.datasets.office_parsing_v2 import office_v2_corpus

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "tests" / "fixtures" / "document_parsing_v2"


@pytest.fixture
def product_database(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'product-v08.db').as_posix()}")
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


class _LLM:
    async def generate(self, prompt: str, **kwargs: object) -> str:
        del prompt, kwargs
        return "ok"

    async def generate_with_schema(self, prompt: str, **kwargs: object) -> str:
        del prompt, kwargs
        return "{}"


def _runtime(
    *,
    vlm_enabled: bool = False,
    office: DoclingOfficeAdapter | None = None,
) -> ProductionDocumentPipeline:
    adaptive = AdaptiveDocumentPipeline(
        PyMuPDFV2Adapter(),
        DoclingLayoutAdapter(),
        PaddleOCRVLAdapter(),
        document_vlm_enabled=vlm_enabled,
    )
    return ProductionDocumentPipeline(
        adaptive,
        office=office,
    )


class _ProductOfficeBackend:
    def convert(
        self, file_data: bytes, filename: str, timeout_seconds: float
    ) -> OfficeBackendResult:
        del file_data, timeout_seconds
        locator_count = 2 if filename.endswith(".docx") else 1
        return OfficeBackendResult(
            items=tuple(
                DoclingItemCandidate(
                    item_id=f"item-{number}",
                    subset_page_number=number,
                    label="section_header" if number == 1 else "paragraph",
                    content_layer="body",
                    text=f"Office evidence {number}",
                    bbox=DoclingBoundingBox(20, 20, 500, 80),
                    reading_order=number - 1,
                    hierarchy_level=0,
                )
                for number in range(1, locator_count + 1)
            ),
            locator_count=locator_count,
            locator_sizes={number: (720, 540) for number in range(1, locator_count + 1)},
        )


async def _store_file(
    product_database: object,
    store: FakeObjectStore,
    *,
    file_id: str,
    filename: str,
) -> None:
    data = (CORPUS / filename).read_bytes()
    path = await store.upload(f"uploads/{filename}", data, "application/pdf")
    with product_database() as session:  # type: ignore[operator]
        session.add(
            FileModel(
                id=file_id,
                workspace_id="local-workspace",
                filename=filename,
                content_type="application/pdf",
                size_bytes=len(data),
                storage_path=path,
                checksum=hashlib.sha256(data).hexdigest(),
                metadata_json={"parse_status": "queued"},
            )
        )
        session.commit()


@pytest.mark.asyncio
async def test_injected_v2_pipeline_is_user_visible_and_persists_canonical_debug(
    product_database,
) -> None:
    store = FakeObjectStore()
    await _store_file(
        product_database, store, file_id="v2-file", filename="native-single-01.pdf"
    )
    processor = PaperAgentProcessor(
        product_database,
        store,
        FakeEmbeddingClient(),
        FakeRerankerClient(),
        _LLM(),
        document_pipeline=_runtime(),
    )

    result = await processor.parse({"_task_id": "v2-task", "file_id": "v2-file"})

    assert result["status"] in {"parsed", "degraded"}
    with product_database() as session:
        parsed = session.query(ParsedDocumentModel).one()
        file_model = session.get(FileModel, "v2-file")
        assert parsed.parser_name == "hybrid-document-v2"
        assert "canonical_document" in parsed.metadata_json
        assert file_model.metadata_json["pipeline_version"] == "v2"

@pytest.mark.asyncio
async def test_legacy_snapshot_task_fails_closed_without_parsing(
    product_database,
) -> None:
    store = FakeObjectStore()
    await _store_file(
        product_database, store, file_id="legacy-file", filename="native-single-02.pdf"
    )
    processor = PaperAgentProcessor(
        product_database,
        store,
        FakeEmbeddingClient(),
        FakeRerankerClient(),
        _LLM(),
        document_pipeline=_runtime(),
    )

    with pytest.raises(ProjectError, match="must be drained or cancelled"):
        await processor.parse(
            {
                "_task_id": "legacy-task",
                "file_id": "legacy-file",
                "document_pipeline_snapshot": {"rollout_percentage": 0},
            }
        )

    with product_database() as session:
        assert session.query(ParsedDocumentModel).count() == 0
    assert not [key for key in store.objects if key.startswith("artifacts/pdf-visuals/")]


@pytest.mark.asyncio
async def test_vlm_disabled_scan_fails_explicitly_without_index(product_database) -> None:
    store = FakeObjectStore()
    await _store_file(
        product_database, store, file_id="scan-file", filename="scan-01.pdf"
    )
    processor = PaperAgentProcessor(
        product_database,
        store,
        FakeEmbeddingClient(),
        FakeRerankerClient(),
        _LLM(),
        document_pipeline=_runtime(vlm_enabled=False),
    )

    with pytest.raises(Exception, match="quality gate"):
        await processor.parse({"_task_id": "scan-task", "file_id": "scan-file"})

    with product_database() as session:
        file_model = session.get(FileModel, "scan-file")
        assert file_model.metadata_json["parse_status"] == "failed"
        assert session.query(ParsedDocumentModel).count() == 0


@pytest.mark.asyncio
async def test_intake_freeze_rejects_new_pdf_intake(product_database) -> None:
    application = PaperAgentApplication(
        product_database,
        FakeObjectStore(),
        FakeTaskQueue(),
        document_parse_intake_enabled=False,
    )

    with pytest.raises(Exception, match="intake is frozen"):
        await application.upload_file(
            "conversation-1",
            "paper.pdf",
            "application/pdf",
            (CORPUS / "native-single-01.pdf").read_bytes(),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sample",
    (office_v2_corpus()[0], office_v2_corpus()[6]),
    ids=lambda sample: sample.case_id,
)
async def test_upload_accepts_approved_office_and_preserves_mime(
    product_database, sample
) -> None:
    queue = FakeTaskQueue()
    application = PaperAgentApplication(product_database, FakeObjectStore(), queue)

    result = await application.upload_file(
        "conversation-1", sample.filename, sample.content_type, sample.data
    )

    with product_database() as session:
        file_model = session.get(FileModel, result["id"])
        assert file_model.content_type == sample.content_type
        assert file_model.metadata_json["document_locator_type"] == sample.locator_type
    queued = queue.tasks[result["task_id"]]
    assert queued.task_type == "document_parse"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sample",
    (office_v2_corpus()[0], office_v2_corpus()[6]),
    ids=lambda sample: f"e2e-{sample.case_id}",
)
async def test_office_upload_parse_index_e2e(product_database, sample) -> None:
    store = FakeObjectStore()
    queue = FakeTaskQueue()
    application = PaperAgentApplication(product_database, store, queue)
    uploaded = await application.upload_file(
        "conversation-1", sample.filename, sample.content_type, sample.data
    )
    processor = PaperAgentProcessor(
        product_database,
        store,
        FakeEmbeddingClient(),
        FakeRerankerClient(),
        _LLM(),
        document_pipeline=_runtime(
            office=DoclingOfficeAdapter(backend=_ProductOfficeBackend()),
        ),
    )

    result = await processor.parse(
        {"_task_id": "office-e2e", "file_id": uploaded["id"]}
    )

    assert result["status"] == "parsed"
    with product_database() as session:
        parsed = session.query(ParsedDocumentModel).one()
        file_model = session.get(FileModel, uploaded["id"])
        canonical = parsed.metadata_json["canonical_document"]
        assert parsed.parser_name == "hybrid-document-v2"
        assert canonical["document_locator_type"] == sample.locator_type
        assert file_model.metadata_json["pipeline_version"] == "v2"
        assert file_model.metadata_json["document_migration"]["write_generation"] == "v2"
