import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from infrastructure.postgres.models import Base
from observability.tracing import SqlAlchemyTraceWriter, TaskTraceService


@pytest.fixture
def tracing(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'trace.db').as_posix()}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    return SqlAlchemyTraceWriter(sessions), TaskTraceService(sessions)


@pytest.mark.asyncio
async def test_task_id_reconstructs_complete_execution_chain(tracing) -> None:
    writer, service = tracing
    task_id = "task-1"
    names = [
        "api.request",
        "requirement.check",
        "skill.activate",
        "plan.created",
        "tool.invoke",
        "subagent.paper_reader",
        "model.call",
        "memory.retrieve",
        "workspace.access",
        "rag.retrieve",
        "verification.complete",
        "task.completed",
    ]
    for name in names:
        await writer.write_trace(
            "trace-1",
            name,
            {"task_id": task_id, "component": name},
        )

    chain = service.reconstruct(task_id)

    assert [span.sequence for span in chain] == list(range(1, len(names) + 1))
    assert [span.span_name for span in chain] == names
    assert service.critical_chain_complete(task_id)


@pytest.mark.asyncio
async def test_trace_redacts_content_and_model_payloads(tracing) -> None:
    writer, service = tracing
    await writer.write_trace(
        "trace-2",
        "workspace.access",
        {"task_id": "task-2", "paper_text": "private paper body", "api_key": "secret"},
    )
    await writer.write_model_call(
        "trace-2",
        "base-4b",
        "private prompt",
        "private response",
        12,
        4,
        10,
    )

    chain = service.reconstruct("task-2")

    assert chain[0].data["paper_text"]["redacted"] is True
    assert chain[0].data["api_key"]["redacted"] is True
    assert "private paper body" not in str(chain[0].data)
