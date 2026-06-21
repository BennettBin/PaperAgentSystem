import pytest
from pydantic import ValidationError

from core.errors import ErrorCode, ProjectError
from infrastructure.fake.observability import FakeTraceWriter
from subagents.paper_reader import (
    PaperCard,
    PaperReaderAgent,
    PaperReaderRequest,
    PaperReaderScope,
)


def card(title: str = "Paper") -> dict:
    return {
        "title": title,
        "research_question": "RQ",
        "methodology": "Method",
        "datasets": ["Dataset"],
        "metrics": ["Accuracy"],
        "results": ["90%"],
        "contributions": ["Contribution"],
        "limitations": ["Small sample"],
        "evidence": [
            {
                "evidence_id": "ev-1",
                "field": "results",
                "quote": "Accuracy reached 90%.",
                "page": 3,
            }
        ],
        "missing_fields": [],
    }


class Backend:
    def __init__(self, response: dict | None = None) -> None:
        self.response = response or card()
        self.calls: list[dict] = []

    async def read(self, **kwargs) -> dict:
        self.calls.append(kwargs)
        return self.response


def scope(file_id: str = "file-1", *, depth: int = 1) -> PaperReaderScope:
    return PaperReaderScope(
        workspace_id="ws-1",
        parent_task_id="parent-1",
        child_task_id="child-1",
        assigned_file_id=file_id,
        trace_id="trace-1",
        depth=depth,
    )


@pytest.mark.asyncio
async def test_agent_uses_single_file_profile_budget_and_no_user_message() -> None:
    backend = Backend()
    traces = FakeTraceWriter()
    result = await PaperReaderAgent(backend, traces).execute(
        scope(),
        PaperReaderRequest(file_id="file-1"),
    )

    assert result.card.title == "Paper"
    assert backend.calls[0]["file_id"] == "file-1"
    assert backend.calls[0]["model_profile"] == "paper_reader_v1"
    assert backend.calls[0]["max_steps"] == 8
    assert traces.traces[-1]["data"]["user_message_emitted"] is False


@pytest.mark.asyncio
async def test_agent_rejects_file_scope_escape_and_nested_agent() -> None:
    agent = PaperReaderAgent(Backend(), FakeTraceWriter())

    with pytest.raises(ProjectError) as file_error:
        await agent.execute(scope(), PaperReaderRequest(file_id="file-2"))
    with pytest.raises(ProjectError) as depth_error:
        await agent.execute(
            scope(depth=2),
            PaperReaderRequest(file_id="file-1"),
        )

    assert file_error.value.code is ErrorCode.PERMISSION_DENIED
    assert depth_error.value.code is ErrorCode.FAILED_PRECONDITION


def test_paper_card_schema_validity_rate() -> None:
    valid = 0
    total = 100
    for index in range(total):
        try:
            PaperCard.model_validate(card(f"Paper {index}"))
            valid += 1
        except ValidationError:
            pass

    assert valid / total >= 0.98


def test_paper_card_reports_missing_fields() -> None:
    value = card()
    value["methodology"] = ""
    value["missing_fields"] = ["methodology"]

    parsed = PaperCard.model_validate(value)

    assert parsed.missing_fields == ["methodology"]
    assert parsed.evidence[0].page == 3
