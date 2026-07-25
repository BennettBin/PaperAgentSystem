from __future__ import annotations

from collections.abc import Callable

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.core.domain.blackboard import BlackboardEntry, BlackboardEntryKind, EvidenceSource
from backend.core.errors import ErrorCode, ProjectError
from backend.infrastructure.fake.blackboard import InMemoryBlackboardRepository
from backend.infrastructure.postgres.blackboard import (
    ManagedSqlAlchemyBlackboardRepository,
    SqlAlchemyBlackboardRepository,
)
from backend.infrastructure.postgres.models import Base


def _entry(*, kind: BlackboardEntryKind, entry_id: str, source: EvidenceSource) -> BlackboardEntry:
    return BlackboardEntry(
        entry_id=entry_id,
        workspace_id="ws-1",
        task_id="task-1",
        kind=kind,
        producer_role="evidence",
        confidence=0.9,
        payload={"text": "supported claim"},
        source=source,
    )


def _fake() -> tuple[InMemoryBlackboardRepository, Callable[[], None]]:
    return InMemoryBlackboardRepository(), lambda: None


def _sql() -> tuple[SqlAlchemyBlackboardRepository, Callable[[], None]]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    return SqlAlchemyBlackboardRepository(session), session.close


def _managed_sql() -> tuple[
    ManagedSqlAlchemyBlackboardRepository,
    Callable[[], None],
]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)
    return ManagedSqlAlchemyBlackboardRepository(sessions), engine.dispose


@pytest.mark.parametrize("factory", [_fake, _sql, _managed_sql])
@pytest.mark.asyncio
async def test_append_only_versions_detect_conflict_and_rebuild(factory) -> None:
    repository, close = factory()
    try:
        source = EvidenceSource(file_id="file-1", citation_id="E1", page_number=3)
        first = _entry(kind=BlackboardEntryKind.EVIDENCE, entry_id="evidence-1", source=source)
        saved = await repository.append(first, expected_version=0)
        assert saved.version == 1
        other_task = first.model_copy(update={"task_id": "task-2"})
        await repository.append(other_task, expected_version=0)
        other_entries = await repository.list_active("ws-1", "task-2")
        assert [entry.entry_id for entry in other_entries] == ["evidence-1"]
        assert other_entries[0].task_id == "task-2"

        revised = saved.next_version(payload={"text": "supported claim", "score": 0.95})
        saved_v2 = await repository.append(revised, expected_version=1)
        with pytest.raises(ProjectError) as exc:
            await repository.append(revised, expected_version=1)
        assert exc.value.code is ErrorCode.FAILED_PRECONDITION

        events = await repository.list_events("ws-1", "task-1")
        assert [event.entry.version for event in events] == [1, 2]
        rebuilt = repository.rebuild(events)
        assert rebuilt == {"evidence-1": saved_v2}
    finally:
        close()


@pytest.mark.parametrize("factory", [_fake, _sql, _managed_sql])
@pytest.mark.asyncio
async def test_workspace_isolation_and_source_deletion_invalidate_retrieval(factory) -> None:
    repository, close = factory()
    try:
        source = EvidenceSource(file_id="file-1", citation_id="E1", page_number=3)
        entry = _entry(kind=BlackboardEntryKind.EVIDENCE, entry_id="evidence-1", source=source)
        await repository.append(entry, expected_version=0)
        derived = _entry(
            kind=BlackboardEntryKind.DRAFT_SECTION,
            entry_id="draft-1",
            source=EvidenceSource(inferred=True),
        )
        await repository.append(derived, expected_version=0)
        assert len(await repository.list_active("ws-1", "task-1")) == 2
        assert await repository.list_active("other-ws", "task-1") == []

        invalidated = await repository.invalidate_source("ws-1", "file", "file-1")
        assert invalidated == 2
        assert await repository.list_active("ws-1", "task-1") == []
        events = await repository.list_events("ws-1", "task-1")
        assert events[-1].event_type == "invalidated"
    finally:
        close()


def test_evidence_requires_pdf_provenance_or_explicit_inference() -> None:
    with pytest.raises(ValidationError):
        _entry(
            kind=BlackboardEntryKind.EVIDENCE,
            entry_id="evidence-1",
            source=EvidenceSource(),
        )
    inferred = _entry(
        kind=BlackboardEntryKind.EVIDENCE,
        entry_id="evidence-2",
        source=EvidenceSource(inferred=True),
    )
    assert inferred.source.inferred
