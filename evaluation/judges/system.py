"""Programmatic-first Judge orchestration with bounded LLM and human fallback."""

from __future__ import annotations

import re
from collections import Counter
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from evaluation.datasets.schema import (
    EvaluationCase,
    JudgeResult,
    JudgeType,
    JudgeVerdict,
)


class JudgeContractError(ValueError):
    """Raised when a Judge violates the structured evidence contract."""


class JudgeInstabilityError(RuntimeError):
    """Raised when repeated Judge decisions are unstable without human fallback."""


class JudgeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case: EvaluationCase
    candidate_answer: str = Field(min_length=1)
    candidate_evidence_ids: list[str] = Field(default_factory=list)


class JudgePort(Protocol):
    def judge(self, judge_input: JudgeInput) -> JudgeResult: ...


class RepeatedJudgeResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    results: list[JudgeResult]
    consistency: float = Field(ge=0, le=1)
    final_result: JudgeResult
    used_human_fallback: bool = False


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


class ProgrammaticJudge:
    version = "programmatic-judge-v1"

    def judge(self, judge_input: JudgeInput) -> JudgeResult:
        case = judge_input.case
        candidate_ids = set(judge_input.candidate_evidence_ids)
        gold_ids = {item.evidence_id for item in case.required_evidence}
        if not candidate_ids <= gold_ids:
            return JudgeResult(
                case_id=case.case_id,
                judge_type=JudgeType.PROGRAMMATIC,
                verdict=JudgeVerdict.FAIL,
                scores={"answer_correctness": 0.0, "citation_validity": 0.0},
                reason_summary="Candidate cites evidence IDs outside the case Gold set.",
                evidence_ids=sorted(candidate_ids & gold_ids),
                judge_version=self.version,
            )
        if case.requires_evidence and not candidate_ids:
            return JudgeResult(
                case_id=case.case_id,
                judge_type=JudgeType.PROGRAMMATIC,
                verdict=JudgeVerdict.FAIL,
                scores={"answer_correctness": 0.0, "citation_recall": 0.0},
                reason_summary="Evidence-required answer contains no candidate evidence IDs.",
                evidence_ids=[],
                judge_version=self.version,
            )
        reference = case.reference_answer
        if reference is not None and _normalize(judge_input.candidate_answer) == _normalize(reference.answer):
            return JudgeResult(
                case_id=case.case_id,
                judge_type=JudgeType.PROGRAMMATIC,
                verdict=JudgeVerdict.PASS,
                scores={"answer_correctness": 1.0, "citation_validity": 1.0},
                reason_summary="Candidate exactly matches the normalized human reference answer and uses valid evidence IDs.",
                evidence_ids=sorted(candidate_ids),
                judge_version=self.version,
            )
        if reference is not None and _normalize(reference.answer) in {"yes.", "no.", "yes", "no"}:
            return JudgeResult(
                case_id=case.case_id,
                judge_type=JudgeType.PROGRAMMATIC,
                verdict=JudgeVerdict.FAIL,
                scores={"answer_correctness": 0.0},
                reason_summary="Candidate does not match the Gold boolean answer.",
                evidence_ids=sorted(candidate_ids),
                judge_version=self.version,
            )
        return JudgeResult(
            case_id=case.case_id,
            judge_type=JudgeType.PROGRAMMATIC,
            verdict=JudgeVerdict.ABSTAIN,
            scores={},
            reason_summary="Deterministic rules cannot establish semantic correctness; supplemental judgment is required.",
            evidence_ids=sorted(candidate_ids),
            judge_version=self.version,
        )


class JudgeSystem:
    def __init__(
        self,
        *,
        programmatic: ProgrammaticJudge,
        llm_judge: JudgePort | None = None,
        human_judge: JudgePort | None = None,
    ) -> None:
        self._programmatic = programmatic
        self._llm_judge = llm_judge
        self._human_judge = human_judge

    def _validate(self, judge_input: JudgeInput, result: JudgeResult) -> JudgeResult:
        if result.case_id != judge_input.case.case_id:
            raise JudgeContractError("Judge returned a result for the wrong case_id")
        gold_ids = {item.evidence_id for item in judge_input.case.required_evidence}
        unknown = set(result.evidence_ids) - gold_ids
        if unknown:
            raise JudgeContractError(f"Judge cited unknown evidence IDs: {sorted(unknown)}")
        return result

    def judge(self, judge_input: JudgeInput) -> JudgeResult:
        result = self._validate(judge_input, self._programmatic.judge(judge_input))
        if result.verdict is not JudgeVerdict.ABSTAIN:
            return result
        if self._llm_judge is not None:
            result = self._validate(judge_input, self._llm_judge.judge(judge_input))
        if result.verdict is JudgeVerdict.ABSTAIN and self._human_judge is not None:
            result = self._validate(judge_input, self._human_judge.judge(judge_input))
        return result

    def judge_repeated(
        self, judge_input: JudgeInput, *, repetitions: int = 3
    ) -> RepeatedJudgeResult:
        if repetitions < 1:
            raise ValueError("Judge repetitions must be positive")
        results = [self.judge(judge_input) for _ in range(repetitions)]
        counts = Counter(result.verdict for result in results)
        consistency = max(counts.values()) / repetitions
        final_result = results[0]
        used_human = False
        if consistency < 0.95:
            if self._human_judge is None:
                raise JudgeInstabilityError(
                    f"Judge consistency {consistency:.3f} is below the 0.95 gate"
                )
            final_result = self._validate(judge_input, self._human_judge.judge(judge_input))
            used_human = True
        return RepeatedJudgeResult(
            case_id=judge_input.case.case_id,
            results=results,
            consistency=consistency,
            final_result=final_result,
            used_human_fallback=used_human,
        )
