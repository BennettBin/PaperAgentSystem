"""
需求和澄清实体
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Optional

from core.domain.enums import ClarificationQuestionType, RequirementCheckStatus
from core.domain.ids import (
    ClarificationRoundId,
    TaskId,
)


@dataclass
class RequirementBrief:
    """需求摘要

    通过需求检查后，系统对任务需求的理解总结。
    """

    task_id: TaskId
    status: RequirementCheckStatus
    sufficient_info: bool
    missing_fields: list[str] = field(default_factory=list)
    constraints: dict = field(default_factory=dict)
    inferred_skill: Optional[str] = None
    confidence: float = 0.0
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def create(
        cls,
        task_id: TaskId,
        sufficient_info: bool,
        missing_fields: Optional[list[str]] = None,
        constraints: Optional[dict] = None,
    ) -> "RequirementBrief":
        """创建需求摘要"""
        return cls(
            task_id=task_id,
            status=RequirementCheckStatus.SUFFICIENT
            if sufficient_info
            else RequirementCheckStatus.NEEDS_CLARIFICATION,
            sufficient_info=sufficient_info,
            missing_fields=missing_fields or [],
            constraints=constraints or {},
        )


@dataclass
class ClarificationQuestion:
    """澄清问题

    需求检查时提出的问题。
    """

    id: str
    round_id: ClarificationRoundId
    type: ClarificationQuestionType
    text: str
    priority: int  # 1-5, 1 最高
    is_required: bool = True
    answer: Optional[str] = None
    answered_at: Optional[datetime] = None

    @classmethod
    def create(
        cls,
        round_id: ClarificationRoundId,
        type: ClarificationQuestionType,
        text: str,
        priority: int = 3,
        is_required: bool = True,
    ) -> "ClarificationQuestion":
        """创建澄清问题"""
        from uuid import uuid4

        return cls(
            id=str(uuid4()),
            round_id=round_id,
            type=type,
            text=text,
            priority=priority,
            is_required=is_required,
        )


@dataclass
class ClarificationRound:
    """澄清轮次

    一轮澄清问题和用户回答。
    """

    id: ClarificationRoundId
    task_id: TaskId
    questions: list[ClarificationQuestion] = field(default_factory=list)
    user_response: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: Optional[datetime] = None

    @classmethod
    def create(cls, task_id: TaskId) -> "ClarificationRound":
        """创建澄清轮次"""
        return cls(
            id=ClarificationRoundId.generate(),
            task_id=task_id,
        )

    def add_question(self, question: ClarificationQuestion) -> None:
        """添加问题"""
        self.questions.append(question)

    def complete_with_response(self, response: str) -> None:
        """完成澄清并记录用户回答"""
        self.user_response = response
        self.completed_at = datetime.now(UTC)
