"""Planner/Completion/Replan ablation executor and promotion-gate report."""

from __future__ import annotations

import json
from enum import StrEnum
from time import monotonic
from typing import Any, Iterable

from pydantic import BaseModel, ConfigDict, Field

from backend.agent_runtime.completion_evaluator import (
    ClaimEvidence,
    CompletionEvaluationInput,
    CompletionEvaluator,
    EvidenceRecord,
)
from backend.agent_runtime.planner import (
    CompletionPredicate,
    ExecutionPlan,
    Observation,
    ObservationStatus,
    PlanBudget,
    PlanStep,
    RegistrySnapshot,
    StepBudget,
    StepType,
)
from backend.agent_runtime.strategy_replanner import ReplanRequest, StrategyReplanner
from evaluation.baseline_evaluation import (
    InMemoryHybridRetriever,
    PageRecord,
    RealModelGateway,
    _answer_prompt,
    _failure_category,
    _json_object,
    _score_case,
)
from evaluation.datasets.schema import EvaluationCase
from evaluation.experiments import (
    ErrorCategory,
    ExperimentCase,
    ExperimentResult,
    ModelCall,
    TraceEvent,
)
from evaluation.metrics.statistics import paired_bootstrap_delta


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlannerAblationKind(StrEnum):
    PLAN_V2 = "plan_v2"
    PLAN_COMPLETION = "plan_completion"
    PLAN_COMPLETION_REPLAN = "plan_completion_replan"


class M06CaseScore(_StrictModel):
    case_id: str
    system_id: str
    difficulty: str
    task_success: bool
    total_tokens: int = Field(ge=0)
    invalid_tool_calls: int = Field(ge=0)
    tool_calls: int = Field(ge=0)
    recovery_attempted: bool = False
    recovery_succeeded: bool = False
    looped: bool = False
    severe_unauthorized_calls: int = Field(default=0, ge=0)


class PlannerAblationExecutor:
    """Use one frozen 4B model and retriever while progressively enabling M features."""

    def __init__(
        self,
        *,
        kind: PlannerAblationKind,
        gateway: RealModelGateway,
        retriever: InMemoryHybridRetriever,
        model: str,
        model_version: str,
    ) -> None:
        self._kind = kind
        self._gateway = gateway
        self._retriever = retriever
        self._model = model
        self._version = model_version
        self._registry = RegistrySnapshot(
            skills=set(),
            tools={"hybrid_retrieval"},
            permitted_tools={"hybrid_retrieval"},
        )

    def execute(
        self,
        experiment_case: ExperimentCase,
        *,
        seed: int,
        attempt: int,
    ) -> ExperimentResult:
        started = monotonic()
        case = EvaluationCase.model_validate(experiment_case.payload)
        calls: list[ModelCall] = []
        trace: list[TraceEvent] = []
        invalid_tool_calls = 0
        tool_calls = 0

        plan_payload = self._call(
            calls,
            profile="m06-planner-v2",
            prompt=_planner_prompt(case),
            max_tokens=512,
        )
        tool = str(plan_payload.get("tool", "hybrid_retrieval"))
        if tool != "hybrid_retrieval":
            invalid_tool_calls += 1
            tool = "hybrid_retrieval"
        raw_queries = plan_payload.get("queries", [])
        queries = [
            str(query).strip()
            for query in raw_queries
            if isinstance(query, str) and str(query).strip()
        ][:3]
        if not queries:
            queries = [case.prompt]
        plan = _execution_plan(case, tool)
        plan.validate_against(self._registry)
        trace.append(
            TraceEvent(
                sequence=1,
                kind="plan",
                data={
                    "version": plan.version,
                    "queries": queries,
                    "invalid_tool_attempts": invalid_tool_calls,
                },
            )
        )

        hits, retrieval_calls = self._retrieve(case, queries, limit=8)
        tool_calls += retrieval_calls
        trace.append(
            TraceEvent(
                sequence=2,
                kind="tool_result",
                data={"tool": tool, "count": len(hits), "pages": [hit.page_number for hit in hits]},
            )
        )
        answer_payload = self._call(
            calls,
            profile="m06-answer-v1",
            prompt=_answer_prompt(case, hits, "retrieve"),
            max_tokens=min(case.resource_budget.max_output_tokens, 384),
        )
        answer, citations = _answer_fields(answer_payload)
        replan_count = 0

        if self._kind is not PlannerAblationKind.PLAN_V2:
            completion = _completion(plan.steps[-1], answer, citations, hits)
            verifier = self._call(
                calls,
                profile="m06-completion-verifier-v1",
                prompt=_verification_prompt(case, answer, citations, hits),
                max_tokens=160,
            )
            supported = bool(verifier.get("supported", False))
            needs_more = bool(verifier.get("needs_more_evidence", not supported))
            inadequate = (
                completion.status is not ObservationStatus.COMPLETE or not supported
            )
            trace.append(
                TraceEvent(
                    sequence=len(trace) + 1,
                    kind="observation",
                    data={
                        "status": completion.status.value,
                        "supported": supported,
                        "needs_more_evidence": needs_more,
                        "missing_items": completion.missing_items,
                    },
                )
            )
            if inadequate and self._kind is PlannerAblationKind.PLAN_COMPLETION:
                answer_payload = self._call(
                    calls,
                    profile="m06-answer-v1",
                    prompt=_repair_answer_prompt(case, answer, citations, hits),
                    max_tokens=min(case.resource_budget.max_output_tokens, 384),
                )
                answer, citations = _answer_fields(answer_payload)
            elif (
                inadequate
                and needs_more
                and self._kind is PlannerAblationKind.PLAN_COMPLETION_REPLAN
            ):
                observation = Observation(
                    step_id="retrieve",
                    status=ObservationStatus.REPLAN,
                    error_code="insufficient_evidence",
                    missing_items=completion.missing_items or ["evidence:insufficient"],
                )
                outcome = StrategyReplanner(self._registry).replan(
                    plan,
                    ReplanRequest(
                        failed_step_id="retrieve",
                        observation=observation,
                    ),
                )
                plan, _ = outcome.patch.apply(plan, self._registry)
                replan_count = plan.replan_count
                expanded_query = str(verifier.get("query", "")).strip()
                expanded_queries = list(
                    dict.fromkeys([*queries, expanded_query or case.prompt])
                )
                hits, retrieval_calls = self._retrieve(
                    case, expanded_queries, limit=16
                )
                tool_calls += retrieval_calls
                trace.append(
                    TraceEvent(
                        sequence=len(trace) + 1,
                        kind="plan",
                        data={
                            "version": plan.version,
                            "strategy": outcome.strategy.value,
                            "reason": outcome.public_reason,
                        },
                    )
                )
                answer_payload = self._call(
                    calls,
                    profile="m06-answer-v1",
                    prompt=_answer_prompt(case, hits, "retrieve"),
                    max_tokens=min(case.resource_budget.max_output_tokens, 384),
                )
                answer, citations = _answer_fields(answer_payload)

        score = _score_case(case, answer, citations, hits)
        failure = _failure_category(case, score, hits)
        trace.extend(
            [
                TraceEvent(
                    sequence=len(trace) + 1,
                    kind="observation",
                    data={"task_success": score["task_success"], "error_category": failure},
                ),
                TraceEvent(
                    sequence=len(trace) + 2,
                    kind="budget",
                    data={
                        "tokens_delta": sum(call.total_tokens for call in calls),
                        "model_calls_delta": len(calls),
                        "tool_calls_delta": tool_calls,
                    },
                ),
            ]
        )
        return ExperimentResult(
            case_id=case.case_id,
            task_id=f"m06-{self._kind.value}-{case.case_id}",
            system_id=self._kind.value,
            passed=bool(score["task_success"]),
            error_code=None if score["task_success"] else f"{failure}_failure",
            error_category=None if score["task_success"] else ErrorCategory(failure),
            model_calls=calls,
            trace=trace,
            output={
                "answer": answer,
                "citations": citations,
                "retrieved": [hit.model_dump(mode="json") for hit in hits],
                "score": score,
                "latency_ms": int((monotonic() - started) * 1000),
                "invalid_tool_calls": invalid_tool_calls,
                "tool_calls": tool_calls,
                "replan_count": replan_count,
                "recovery_attempted": bool(replan_count),
                "recovery_succeeded": bool(replan_count and score["task_success"]),
                "looped": False,
                "severe_unauthorized_calls": 0,
                "seed": seed,
                "attempt": attempt,
            },
        )

    def _retrieve(
        self,
        case: EvaluationCase,
        queries: list[str],
        *,
        limit: int,
    ) -> tuple[list[PageRecord], int]:
        by_location: dict[tuple[str, int], PageRecord] = {}
        for query in queries:
            for hit in self._retriever.retrieve(
                query,
                set(case.paper_ids),
                limit=limit,
                section_aware=True,
            ):
                by_location.setdefault((hit.paper_id, hit.page_number), hit)
        merged = list(by_location.values())[:limit]
        return [
            hit.model_copy(update={"evidence_id": f"E{index}"})
            for index, hit in enumerate(merged, 1)
        ], len(queries)

    def _call(
        self,
        calls: list[ModelCall],
        *,
        profile: str,
        prompt: str,
        max_tokens: int,
    ) -> dict[str, Any]:
        content, input_tokens, output_tokens, latency_ms = self._gateway.complete(
            model=self._model,
            profile=profile,
            prompt=prompt,
            max_tokens=max_tokens,
        )
        calls.append(
            ModelCall(
                model=self._model,
                profile=profile,
                version=self._version,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency_ms,
            )
        )
        return _json_object(content)


def build_m06_report(
    rows: Iterable[M06CaseScore | dict[str, Any]],
    *,
    truth_class: str,
) -> dict[str, Any]:
    records = [
        row if isinstance(row, M06CaseScore) else M06CaseScore.model_validate(row)
        for row in rows
    ]
    grouped: dict[str, list[M06CaseScore]] = {}
    for row in records:
        grouped.setdefault(row.system_id, []).append(row)
    old_ids = [name for name in ("fixed_workflow", "current_react") if name in grouped]
    candidate_id = "plan_completion_replan"
    if not old_ids or candidate_id not in grouped:
        raise ValueError("M06 report requires an old baseline and full candidate")

    def eligible(values: list[M06CaseScore]) -> list[M06CaseScore]:
        return [row for row in values if row.difficulty in {"L3", "L4", "L5"}]

    old_success = {
        name: _rate(eligible(grouped[name]), "task_success") for name in old_ids
    }
    best_old_id = max(old_success, key=lambda name: old_success[name])
    best_old = grouped[best_old_id]
    candidate = grouped[candidate_id]
    candidate_success = _rate(eligible(candidate), "task_success")
    best_success = old_success[best_old_id]
    old_by_case = {row.case_id: row for row in eligible(best_old)}
    candidate_by_case = {row.case_id: row for row in eligible(candidate)}
    paired_ids = sorted(set(old_by_case) & set(candidate_by_case))
    success_delta_ci = paired_bootstrap_delta(
        [float(candidate_by_case[case_id].task_success) for case_id in paired_ids],
        [float(old_by_case[case_id].task_success) for case_id in paired_ids],
        samples=2000,
        seed=20260721,
    )
    old_invalid = _invalid_rate(best_old)
    candidate_invalid = _invalid_rate(candidate)
    invalid_reduction = (
        (old_invalid - candidate_invalid) / old_invalid if old_invalid > 0 else 0.0
    )
    old_recovery = _recovery_rate(best_old)
    candidate_recovery = _recovery_rate(candidate)
    old_token_per_success = _tokens_per_success(best_old)
    candidate_token_per_success = _tokens_per_success(candidate)
    token_increase = (
        (candidate_token_per_success - old_token_per_success) / old_token_per_success
        if old_token_per_success is not None
        and candidate_token_per_success is not None
        and old_token_per_success > 0
        else None
    )
    gates = {
        "l3_l5_success_improves_8pp": candidate_success - best_success >= 0.08,
        "invalid_tool_call_rate_reduces_25pct": invalid_reduction >= 0.25,
        "fault_recovery_improves_15pp": candidate_recovery - old_recovery >= 0.15,
        "token_per_success_increase_lte_15pct": (
            token_increase is not None and token_increase <= 0.15
        ),
        "zero_loops_and_unauthorized_calls": not any(
            row.looped or row.severe_unauthorized_calls for row in records
        ),
    }
    return {
        "schema_version": "1.0",
        "truth_class": truth_class,
        "case_score_count": len(records),
        "best_old_baseline": best_old_id,
        "metrics": {
            "best_old_l3_l5_task_success": best_success,
            "candidate_l3_l5_task_success": candidate_success,
            "task_success_delta": candidate_success - best_success,
            "task_success_delta_ci95": success_delta_ci.model_dump(mode="json"),
            "best_old_invalid_tool_call_rate": old_invalid,
            "candidate_invalid_tool_call_rate": candidate_invalid,
            "invalid_tool_call_rate_reduction": invalid_reduction,
            "best_old_recovery_rate": old_recovery,
            "candidate_recovery_rate": candidate_recovery,
            "recovery_rate_delta": candidate_recovery - old_recovery,
            "best_old_tokens_per_success": old_token_per_success,
            "candidate_tokens_per_success": candidate_token_per_success,
            "token_per_success_increase": token_increase,
        },
        "gates": gates,
        "all_gates_passed": all(gates.values()),
    }


def _execution_plan(case: EvaluationCase, tool: str) -> ExecutionPlan:
    return ExecutionPlan(
        goal=case.prompt,
        global_budget=PlanBudget(
            max_tokens=case.resource_budget.max_input_tokens
            + case.resource_budget.max_output_tokens,
            max_tool_calls=case.resource_budget.max_tool_calls,
            max_subagent_calls=0,
            max_duration_ms=case.resource_budget.max_latency_ms,
        ),
        steps=[
            PlanStep(
                step_id="retrieve",
                action="Retrieve evidence using task-specific queries",
                step_type=StepType.TOOL_CALL,
                tool_name=tool,
                budget=StepBudget(max_tool_calls=1),
                completion_predicate=CompletionPredicate(
                    kind="evidence_acquired", minimum_evidence=1
                ),
            ),
            PlanStep(
                step_id="answer",
                action="Answer with citations",
                depends_on=["retrieve"],
                completion_predicate=CompletionPredicate(
                    kind="answer_with_evidence",
                    required_fields=["answer"],
                    minimum_evidence=1 if case.requires_evidence else 0,
                ),
            ),
        ],
    )


def _completion(
    step: PlanStep,
    answer: str,
    citations: list[str],
    hits: list[PageRecord],
) -> Observation:
    claim = ClaimEvidence(
        claim_id="answer-claim",
        text=answer or "empty answer",
        evidence_ids=citations,
        factual=True,
    )
    evidence = [
        EvidenceRecord(
            evidence_id=hit.evidence_id,
            source_id=hit.paper_id,
            page_number=hit.page_number,
            claim_ids=["answer-claim"],
        )
        for hit in hits
    ]
    return CompletionEvaluator().evaluate(
        step,
        CompletionEvaluationInput(
            output={"answer": answer, "citations": citations},
            claims=[claim],
            evidence=evidence,
        ),
    ).observation


def _planner_prompt(case: EvaluationCase) -> str:
    return json.dumps(
        {
            "instruction": "Return JSON only with permitted Tool and up to three retrieval queries.",
            "schema": {"tool": "hybrid_retrieval", "queries": ["string"]},
            "allowed_tools": ["hybrid_retrieval"],
            "task": case.prompt,
            "paper_ids": case.paper_ids,
            "max_queries": 3,
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _verification_prompt(
    case: EvaluationCase,
    answer: str,
    citations: list[str],
    hits: list[PageRecord],
) -> str:
    evidence = "\n".join(
        f"[{hit.evidence_id}] {hit.text[:1200]}" for hit in hits
    )
    return (
        "Return JSON only: {\"supported\":true|false,"
        "\"needs_more_evidence\":true|false,\"query\":\"...\"}. "
        "Judge only against supplied evidence and do not reveal hidden reasoning.\n"
        f"Task: {case.prompt}\nAnswer: {answer}\nCitations: {citations}\nEvidence:\n{evidence}"
    )


def _repair_answer_prompt(
    case: EvaluationCase,
    answer: str,
    citations: list[str],
    hits: list[PageRecord],
) -> str:
    return (
        _answer_prompt(case, hits, "retrieve")
        + f"\nPrevious answer failed completion checks: {answer} {citations}. Repair it using only supplied evidence."
    )


def _answer_fields(payload: dict[str, Any]) -> tuple[str, list[str]]:
    answer = str(payload.get("answer", "")).strip()
    citations = [
        value
        for value in payload.get("citations", [])
        if isinstance(value, str) and value.startswith("E") and value[1:].isdigit()
    ]
    return answer, citations


def _rate(rows: list[M06CaseScore], field: str) -> float:
    return (
        sum(bool(getattr(row, field)) for row in rows) / len(rows) if rows else 0.0
    )


def _invalid_rate(rows: list[M06CaseScore]) -> float:
    calls = sum(row.tool_calls for row in rows)
    return sum(row.invalid_tool_calls for row in rows) / calls if calls else 0.0


def _recovery_rate(rows: list[M06CaseScore]) -> float:
    attempted = [row for row in rows if row.recovery_attempted]
    return _rate(attempted, "recovery_succeeded")


def _tokens_per_success(rows: list[M06CaseScore]) -> float | None:
    successes = sum(row.task_success for row in rows)
    return sum(row.total_tokens for row in rows) / successes if successes else None
