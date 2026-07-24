import asyncio
from pathlib import Path

import docker
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from testcontainers.postgres import PostgresContainer

from backend.core.domain.ids import ConversationId, WorkspaceId
from backend.infrastructure.postgres.models import (
    ConversationModel,
    DocumentChunkModel,
    MessageModel,
    ParsedDocumentModel,
    UserModel,
    WorkspaceModel,
)
from backend.memory import ShortTermMemoryService
from backend.rag.retrieval import HybridRetriever


class IntegrationEmbeddings:
    async def embed(self, text: str) -> list[float]:
        return [1.0 if "calibration" in text.lower() else 0.0] + [0.0] * 1023

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [await self.embed(text) for text in texts]


class IntegrationReranker:
    async def rerank(self, query: str, documents: list[str], top_k: int = 5):
        return [
            (index, float("calibration" in document.lower()))
            for index, document in enumerate(documents[:top_k])
        ]


def docker_available() -> bool:
    try:
        client = docker.from_env()
        client.ping()
        return True
    except Exception:
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not docker_available(), reason="Docker daemon is unavailable"),
]


def test_postgres_empty_database_migration_upgrade_downgrade():
    root = Path(__file__).resolve().parents[2]
    with PostgresContainer("pgvector/pgvector:pg16") as postgres:
        url = postgres.get_connection_url().replace("postgresql+psycopg2", "postgresql+psycopg")
        config = Config(str(root / "infrastructure" / "database" / "alembic.ini"))
        config.set_main_option("sqlalchemy.url", url)

        command.upgrade(config, "head")
        engine = create_engine(url)
        tables = inspect(engine).get_table_names()
        assert {"users", "workspaces", "conversations", "tasks", "files"} <= set(tables)
        assert {"parsed_documents", "document_chunks", "subagent_runs"} <= set(tables)
        with engine.connect() as connection:
            indexes = {
                row[0]
                for row in connection.exec_driver_sql(
                    "SELECT indexname FROM pg_indexes "
                    "WHERE tablename = 'document_chunks'"
                )
            }
            column_type = connection.exec_driver_sql(
                "SELECT format_type(a.atttypid, a.atttypmod) "
                "FROM pg_attribute a "
                "JOIN pg_class c ON c.oid = a.attrelid "
                "WHERE c.relname = 'document_chunks' "
                "AND a.attname = 'embedding'"
            ).scalar_one()
        assert "ix_document_chunks_embedding_hnsw" in indexes
        assert "ix_document_chunks_fts" in indexes
        assert column_type == "vector(1024)"
        factory = sessionmaker(engine, expire_on_commit=False)
        with factory() as session:
            session.add(
                ParsedDocumentModel(
                    id="integration-document",
                    workspace_id="integration-workspace",
                    file_id="integration-file",
                    checksum="integration-checksum",
                    parser_name="fixture",
                    parser_version="1",
                    page_count=1,
                    quality_score=100,
                )
            )
            session.flush()
            session.add(
                DocumentChunkModel(
                    id="integration-chunk",
                    workspace_id="integration-workspace",
                    file_id="integration-file",
                    document_id="integration-document",
                    parent_chunk_id="integration-parent",
                    level="child",
                    section_path=["Results"],
                    text="Calibration accuracy improved.",
                    page_start=1,
                    page_end=1,
                    bbox_json=[0, 0, 100, 100],
                    source_block_ids=["block-1"],
                    embedding=[1.0] + [0.0] * 1023,
                    embedding_model="integration",
                    searchable_text="Calibration accuracy improved.",
                )
            )
            session.commit()
        hits = asyncio.run(
            HybridRetriever(
                factory,
                IntegrationEmbeddings(),
                IntegrationReranker(),
            ).search(
                "calibration accuracy",
                workspace_id="integration-workspace",
                file_ids={"integration-file"},
            )
        )
        assert hits[0].chunk_id == "integration-chunk"
        with factory() as session:
            session.add(
                UserModel(
                    id="memory-user",
                    email="memory@example.test",
                    name="Memory",
                )
            )
            session.add(
                WorkspaceModel(
                    id="memory-workspace",
                    user_id="memory-user",
                    name="Memory workspace",
                )
            )
            session.commit()
            session.add(
                ConversationModel(
                    id="memory-conversation",
                    workspace_id="memory-workspace",
                    user_id="memory-user",
                    title="Memory",
                )
            )
            session.commit()
            for index in range(8):
                session.add(
                    MessageModel(
                        id=f"memory-message-{index}",
                        workspace_id="memory-workspace",
                        conversation_id="memory-conversation",
                        role="user" if index % 2 == 0 else "assistant",
                        type="text",
                        content=f"PostgreSQL memory source {index}",
                        metadata_json={},
                    )
                )
            session.commit()
        memory = ShortTermMemoryService(
            factory,
            IntegrationEmbeddings(),
            message_threshold=8,
        )
        first_segment = asyncio.run(
            memory.summarize_if_needed(
                WorkspaceId(value="memory-workspace"),
                ConversationId(value="memory-conversation"),
            )
        )
        second_segment = asyncio.run(
            memory.summarize_if_needed(
                WorkspaceId(value="memory-workspace"),
                ConversationId(value="memory-conversation"),
            )
        )
        assert first_segment
        assert second_segment == first_segment
        with engine.connect() as connection:
            assert connection.scalar(
                text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
            ) == 1

        command.downgrade(config, "base")
        assert inspect(engine).get_table_names() == ["alembic_version"]
