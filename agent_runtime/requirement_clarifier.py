"""Requirement completeness check with bounded clarification rounds."""

import re
from dataclasses import dataclass, field
from typing import Protocol

from core.domain.enums import RequirementCheckStatus
from core.domain.ids import TaskId
from core.domain.requirement import RequirementBrief


class RequirementRetriever(Protocol):
    async def search(self, query: str, *, workspace_id: str, limit: int) -> list[str]: ...


@dataclass(frozen=True, slots=True)
class RequirementInput:
    task_id: TaskId
    workspace_id: str
    request: str


@dataclass(slots=True)
class ClarificationContext:
    task_id: TaskId
    workspace_id: str = ""
    original_request: str = ""
    round_count: int = 0
    waiting_user: bool = False
    evidence: list[str] = field(default_factory=list)
    answers: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class RequirementCheckResult:
    brief: RequirementBrief
    questions: list[str]
    context: ClarificationContext


class RequirementClarifier:
    """Deterministic baseline; a model may later enrich extraction, not policy."""

    MAX_ROUNDS = 2

    def __init__(
        self,
        memory_retriever: RequirementRetriever,
        workspace_retriever: RequirementRetriever,
    ) -> None:
        self._memory = memory_retriever
        self._workspace = workspace_retriever

    async def check(
        self,
        item: RequirementInput,
        context: ClarificationContext | None = None,
    ) -> RequirementCheckResult:
        current = context or ClarificationContext(task_id=item.task_id)
        if current.task_id != item.task_id:
            raise ValueError("Clarification must resume the original task")
        current.workspace_id = item.workspace_id or current.workspace_id
        current.original_request = item.request or current.original_request
        memory = await self._memory.search(
            current.original_request,
            workspace_id=current.workspace_id,
            limit=5,
        )
        workspace = await self._workspace.search(
            current.original_request,
            workspace_id=current.workspace_id,
            limit=5,
        )
        current.evidence = [*memory, *workspace]
        combined = " ".join(
            [current.original_request, *current.answers, *current.evidence]
        )
        constraints = self._extract_constraints(combined)
        missing = self._missing_fields(current.original_request, constraints)
        if not missing:
            current.waiting_user = False
            brief = RequirementBrief.create(item.task_id, True, constraints=constraints)
            brief.confidence = 0.95
            return RequirementCheckResult(brief, [], current)
        if current.round_count >= self.MAX_ROUNDS:
            current.waiting_user = False
            brief = RequirementBrief.create(
                item.task_id,
                False,
                missing_fields=missing,
                constraints=constraints,
            )
            brief.status = RequirementCheckStatus.DEFERRED
            brief.confidence = 0.6
            return RequirementCheckResult(brief, [], current)
        questions = [self._question(field) for field in missing[:5]]
        current.waiting_user = True
        brief = RequirementBrief.create(
            item.task_id,
            False,
            missing_fields=missing,
            constraints=constraints,
        )
        brief.confidence = 0.9
        return RequirementCheckResult(brief, questions, current)

    async def resume(
        self,
        context: ClarificationContext,
        user_answer: str,
    ) -> RequirementCheckResult:
        context.answers.append(user_answer)
        context.round_count += 1
        context.waiting_user = False
        return await self.check(
            RequirementInput(
                task_id=context.task_id,
                workspace_id=context.workspace_id,
                request=context.original_request,
            ),
            context,
        )

    @staticmethod
    def _extract_constraints(text: str) -> dict:
        constraints: dict = {}
        files = re.findall(r"[\w.-]+\.pdf", text, flags=re.IGNORECASE)
        unique_files = list(dict.fromkeys(files))
        if len(unique_files) == 1:
            constraints["source"] = unique_files[0]
        elif unique_files:
            constraints["sources"] = unique_files
        if "中文" in text or "输出中文" in text:
            constraints["output_language"] = "zh"
        if "方法和实验" in text:
            constraints["focus"] = "方法和实验"
        elif "方法" in text:
            constraints["focus"] = "方法"
        elif "实验" in text:
            constraints["focus"] = "实验"
        return constraints

    @staticmethod
    def _missing_fields(request: str, constraints: dict) -> list[str]:
        missing = []
        action_words = ("总结", "比较", "提取", "验证", "分析", "改写", "翻译")
        if not any(word in request for word in action_words):
            missing.append("goal")
        source_count = len(constraints.get("sources", [])) + int("source" in constraints)
        if source_count == 0:
            missing.append("source")
        if "比较" in request and source_count < 2:
            missing.append("comparison_sources")
        return list(dict.fromkeys(missing))

    @staticmethod
    def _question(field: str) -> str:
        return {
            "goal": "你希望完成什么具体任务？",
            "source": "要处理哪篇论文或哪些工作区文件？",
            "comparison_sources": "请提供至少两篇要比较的论文。",
        }[field]
