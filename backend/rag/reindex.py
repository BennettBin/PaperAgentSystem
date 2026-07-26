"""Re-vectorize stored chunks without reparsing source PDFs."""

from __future__ import annotations

import argparse
import asyncio
import logging

from sqlalchemy import select, update

from backend.infrastructure.config import InfrastructureSettings
from backend.infrastructure.postgres.database import Database
from backend.infrastructure.postgres.models import DocumentChunkModel, ParsedDocumentModel
from backend.infrastructure.postgres.schema import ensure_database_schema
from backend.rag.embeddings import build_embedding_client, require_embedding_profile

LOGGER = logging.getLogger(__name__)


async def reindex_chunks(
    settings: InfrastructureSettings,
    *,
    workspace_id: str | None = None,
    file_id: str | None = None,
    only_stale: bool = False,
    dry_run: bool = False,
) -> int:
    database = Database(settings.database_url)
    ensure_database_schema(database.engine)
    embeddings = build_embedding_client(settings)
    profile = require_embedding_profile(embeddings)
    with database.session_factory() as session:
        statement = select(ParsedDocumentModel.id).order_by(ParsedDocumentModel.id)
        if workspace_id:
            statement = statement.where(ParsedDocumentModel.workspace_id == workspace_id)
        if file_id:
            statement = statement.where(ParsedDocumentModel.file_id == file_id)
        document_ids = list(session.scalars(statement))
    if dry_run:
        LOGGER.info(
            "Embedding reindex dry-run documents=%d target=%s",
            len(document_ids),
            profile.fingerprint,
        )
        return len(document_ids)

    completed = 0
    for document_id in document_ids:
        with database.session_factory() as session:
            chunk_statement = (
                select(DocumentChunkModel)
                .where(DocumentChunkModel.document_id == document_id)
                .order_by(DocumentChunkModel.created_at, DocumentChunkModel.id)
            )
            if only_stale:
                chunk_statement = chunk_statement.where(
                    (DocumentChunkModel.embedding_status != "ready")
                    | (DocumentChunkModel.embedding_fingerprint != profile.fingerprint)
                )
            chunks = list(session.scalars(chunk_statement))
            if not chunks:
                continue
            chunk_ids = [chunk.id for chunk in chunks]
            texts = [chunk.text for chunk in chunks]
            session.execute(
                update(DocumentChunkModel)
                .where(DocumentChunkModel.id.in_(chunk_ids))
                .values(embedding_status="stale")
            )
            session.commit()
        vectors = await embeddings.embed_batch(texts)
        actual_profile = require_embedding_profile(embeddings)
        if len(vectors) != len(chunk_ids):
            raise RuntimeError("Embedding provider returned an unexpected vector count")
        with database.session_factory() as session:
            for chunk_id, vector in zip(chunk_ids, vectors):
                if len(vector) != actual_profile.dimension:
                    raise RuntimeError(
                        f"Embedding dimension mismatch for {chunk_id}: {len(vector)}"
                    )
                session.execute(
                    update(DocumentChunkModel)
                    .where(DocumentChunkModel.id == chunk_id)
                    .values(
                        embedding=vector,
                        embedding_provider=actual_profile.provider,
                        embedding_model=actual_profile.model_name,
                        embedding_version=actual_profile.model_version,
                        embedding_dimension=actual_profile.dimension,
                        embedding_max_length=actual_profile.max_length,
                        embedding_normalized=actual_profile.normalized,
                        embedding_fingerprint=actual_profile.fingerprint,
                        embedding_status="ready",
                    )
                )
            document = session.get(ParsedDocumentModel, document_id)
            if document is not None:
                document.metadata_json = {
                    **(document.metadata_json or {}),
                    "embedding_profile": {
                        "provider": actual_profile.provider,
                        "model_name": actual_profile.model_name,
                        "model_version": actual_profile.model_version,
                        "dimension": actual_profile.dimension,
                        "max_length": actual_profile.max_length,
                        "normalized": actual_profile.normalized,
                        "fingerprint": actual_profile.fingerprint,
                    },
                }
            session.commit()
        completed += 1
        LOGGER.info(
            "Embedding reindex document completed document_id=%s chunks=%d profile=%s",
            document_id,
            len(chunk_ids),
            actual_profile.fingerprint,
        )
    return completed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=("hash", "bge_m3", "auto"))
    parser.add_argument("--workspace-id")
    parser.add_argument("--file-id")
    parser.add_argument("--batch-size", type=int)
    parser.add_argument("--only-stale", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    settings = InfrastructureSettings()
    updates: dict[str, object] = {}
    if args.provider:
        updates["embedding_provider"] = args.provider
    if args.batch_size:
        updates["embedding_batch_size"] = args.batch_size
    if updates:
        settings = settings.model_copy(update=updates)
    logging.basicConfig(level=logging.INFO)
    completed = asyncio.run(
        reindex_chunks(
            settings,
            workspace_id=args.workspace_id,
            file_id=args.file_id,
            only_stale=args.only_stale,
            dry_run=args.dry_run,
        )
    )
    print(f"documents_processed={completed}")


if __name__ == "__main__":
    main()
