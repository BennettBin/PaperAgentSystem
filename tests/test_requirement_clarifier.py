import pytest

from agent_runtime.requirement_clarifier import (
    ClarificationContext,
    RequirementClarifier,
    RequirementInput,
)
from core.domain.enums import RequirementCheckStatus
from core.domain.ids import TaskId


class RecordingRetriever:
    def __init__(self, values: list[str]) -> None:
        self.values = values
        self.queries: list[str] = []

    async def search(self, query: str, *, workspace_id: str, limit: int) -> list[str]:
        self.queries.append(query)
        return self.values[:limit]


@pytest.mark.asyncio
async def test_clarifier_searches_memory_and_workspace_before_asking() -> None:
    memory = RecordingRetriever(["用户偏好：输出中文表格"])
    workspace = RecordingRetriever(["文件：paper.pdf"])
    clarifier = RequirementClarifier(memory, workspace)

    result = await clarifier.check(
        RequirementInput(
            task_id=TaskId.generate(),
            workspace_id="ws-1",
            request="总结这篇论文",
        )
    )

    assert memory.queries and workspace.queries
    assert result.brief.sufficient_info
    assert result.brief.constraints["output_language"] == "zh"
    assert result.brief.constraints["source"] == "paper.pdf"
    assert result.questions == []


@pytest.mark.asyncio
async def test_clarifier_asks_one_to_five_questions_and_waits_on_same_task() -> None:
    task_id = TaskId.generate()
    clarifier = RequirementClarifier(RecordingRetriever([]), RecordingRetriever([]))

    result = await clarifier.check(
        RequirementInput(task_id=task_id, workspace_id="ws-1", request="帮我处理一下")
    )

    assert 1 <= len(result.questions) <= 5
    assert result.brief.status is RequirementCheckStatus.NEEDS_CLARIFICATION
    assert result.context.waiting_user
    assert result.context.task_id == task_id


@pytest.mark.asyncio
async def test_clarifier_continues_best_effort_after_two_rounds() -> None:
    task_id = TaskId.generate()
    clarifier = RequirementClarifier(RecordingRetriever([]), RecordingRetriever([]))
    context = ClarificationContext(task_id=task_id, round_count=2)

    result = await clarifier.check(
        RequirementInput(task_id=task_id, workspace_id="ws-1", request="处理一下"),
        context,
    )

    assert result.questions == []
    assert result.brief.status is RequirementCheckStatus.DEFERRED
    assert result.context.task_id == task_id
    assert not result.context.waiting_user


@pytest.mark.asyncio
async def test_answer_resumes_original_task_and_merges_constraints() -> None:
    task_id = TaskId.generate()
    clarifier = RequirementClarifier(RecordingRetriever([]), RecordingRetriever([]))
    first = await clarifier.check(
        RequirementInput(task_id=task_id, workspace_id="ws-1", request="比较论文"),
    )

    resumed = await clarifier.resume(first.context, "比较方法和实验，来源是 a.pdf 和 b.pdf")

    assert resumed.context.task_id == task_id
    assert resumed.context.round_count == 1
    assert resumed.brief.constraints["focus"] == "方法和实验"
    assert resumed.brief.constraints["sources"] == ["a.pdf", "b.pdf"]


@pytest.mark.asyncio
async def test_requirement_evaluation_thresholds() -> None:
    clarifier = RequirementClarifier(RecordingRetriever([]), RecordingRetriever([]))
    cases = [
        ("总结 paper.pdf", True),
        ("比较 a.pdf 和 b.pdf 的方法", True),
        ("提取 paper.pdf 的结论", True),
        ("帮我处理一下", False),
        ("总结一下", False),
        ("比较论文", False),
    ] * 34
    predictions = []
    for index, (request, expected) in enumerate(cases):
        result = await clarifier.check(
            RequirementInput(
                task_id=TaskId.generate(),
                workspace_id=f"ws-{index}",
                request=request,
            )
        )
        predictions.append(result.brief.sufficient_info)

    tp = sum(pred and expected for pred, (_, expected) in zip(predictions, cases))
    tn = sum(not pred and not expected for pred, (_, expected) in zip(predictions, cases))
    fp = sum(pred and not expected for pred, (_, expected) in zip(predictions, cases))
    fn = sum(not pred and expected for pred, (_, expected) in zip(predictions, cases))
    positive_f1 = 2 * tp / (2 * tp + fp + fn)
    negative_f1 = 2 * tn / (2 * tn + fp + fn)
    missing_recall = tn / (tn + fp)
    unnecessary_question_rate = fn / (tp + fn)

    assert (positive_f1 + negative_f1) / 2 >= 0.90
    assert missing_recall >= 0.95
    assert unnecessary_question_rate <= 0.10
