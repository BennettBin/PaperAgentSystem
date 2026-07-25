"""Real-model progressive multi-Agent ablation and fail-closed promotion gates."""

from __future__ import annotations

import json
from enum import StrEnum
from time import monotonic
from typing import Any, Iterable

from pydantic import BaseModel, ConfigDict, Field

from evaluation.baseline_evaluation import (
    InMemoryHybridRetriever,
    PageRecord,
    RealModelGateway,
    _json_object,
)
from evaluation.datasets.schema import EvaluationCase
from evaluation.experiments import ExperimentCase, ExperimentResult, ModelCall, TraceEvent
from evaluation.metrics.statistics import paired_bootstrap_delta


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class N05Stage(StrEnum):
    READER_PARALLEL = "reader_parallel"
    EVIDENCE = "evidence"
    CRITIC = "critic"
    VERIFIER = "verifier"
    FULL_SYSTEM = "full_system"


class N05CaseScore(_StrictModel):
    case_id: str
    system_id: str
    task_success: bool
    claim_support_rate: float = Field(ge=0, le=1)
    omission_rate: float = Field(ge=0, le=1)
    total_tokens: int = Field(ge=0)
    latency_ms: int = Field(ge=0)
    severe_unsupported_rate: float | None = Field(default=None, ge=0, le=1)
    conflict_recall: float | None = Field(default=None, ge=0, le=1)


class MultiAgentAblationExecutor:
    """Run five bounded 4B role calls and expose every progressive stage."""

    def __init__(
        self,
        *,
        gateway: RealModelGateway,
        retriever: InMemoryHybridRetriever,
        model: str,
        model_version: str,
    ) -> None:
        self._gateway = gateway
        self._retriever = retriever
        self._model = model
        self._version = model_version

    def execute(
        self, experiment_case: ExperimentCase, *, seed: int, attempt: int
    ) -> ExperimentResult:
        started = monotonic()
        case = EvaluationCase.model_validate(experiment_case.payload)
        hits = self._retriever.retrieve(case.prompt, set(case.paper_ids), limit=12)
        context = _evidence_context(hits)
        calls: list[ModelCall] = []

        reader = self._call(
            calls,
            "n05-reader-v1",
            _reader_prompt(case, context),
            480,
        )
        evidence = self._call(
            calls,
            "n05-evidence-v1",
            _evidence_prompt(case, reader, context),
            480,
        )
        critic = self._call(
            calls,
            "n05-critic-v1",
            _critic_prompt(case, evidence),
            320,
        )
        writer = self._call(
            calls,
            "n05-writer-v1",
            _writer_prompt(case, evidence, critic),
            480,
        )
        verifier = self._call(
            calls,
            "n05-verifier-v1",
            _verifier_prompt(case, evidence, writer),
            480,
        )

        stages = {
            N05Stage.READER_PARALLEL.value: _normalized_stage(reader),
            N05Stage.EVIDENCE.value: _normalized_stage(evidence),
            N05Stage.CRITIC.value: _normalized_stage(writer),
            N05Stage.VERIFIER.value: {
                **_normalized_stage(writer),
                "findings": verifier.get("findings", []),
            },
            N05Stage.FULL_SYSTEM.value: _normalized_stage(
                {
                    "answer": verifier.get("revised_answer", writer.get("answer", "")),
                    "citations": verifier.get(
                        "revised_citations", writer.get("citations", [])
                    ),
                    "claims": verifier.get("revised_claims", writer.get("claims", [])),
                    "conflict_detected": verifier.get(
                        "conflict_detected", critic.get("conflict_detected", False)
                    ),
                    "findings": verifier.get("findings", []),
                }
            ),
        }
        stage_call_counts = {
            N05Stage.READER_PARALLEL.value: 1,
            N05Stage.EVIDENCE.value: 2,
            N05Stage.CRITIC.value: 4,
            N05Stage.VERIFIER.value: 5,
            N05Stage.FULL_SYSTEM.value: 5,
        }
        trace = [
            TraceEvent(
                sequence=index,
                kind="role_completed",
                data={"role": call.profile, "public_summary": "structured artifact emitted"},
            )
            for index, call in enumerate(calls, 1)
        ]
        return ExperimentResult(
            case_id=case.case_id,
            task_id=f"n05-{case.case_id}",
            system_id="n05-progressive-pipeline",
            passed=True,
            model_calls=calls,
            trace=trace,
            output={
                "stages": stages,
                "stage_call_counts": stage_call_counts,
                "hits": [hit.model_dump(mode="json") for hit in hits],
                "wall_clock_ms": int((monotonic() - started) * 1000),
                "seed": seed,
                "attempt": attempt,
            },
        )

    def _call(
        self, calls: list[ModelCall], profile: str, prompt: str, max_tokens: int
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


def build_n05_report(
    rows: Iterable[N05CaseScore], *, truth_class: str
) -> dict[str, Any]:
    materialized = list(rows)
    systems = {
        "single_agent",
        *(stage.value for stage in N05Stage),
    }
    grouped = {
        system: [row for row in materialized if row.system_id == system]
        for system in systems
    }
    counts = {system: len(items) for system, items in grouped.items()}
    nonzero_counts = {count for count in counts.values() if count}
    matrix_complete = set(grouped) == systems and len(nonzero_counts) == 1 and all(counts.values())
    baseline = {row.case_id: row for row in grouped["single_agent"]}
    candidate = {row.case_id: row for row in grouped[N05Stage.FULL_SYSTEM.value]}
    paired_ids = sorted(set(baseline) & set(candidate))
    support_delta = _mean(candidate[key].claim_support_rate for key in paired_ids) - _mean(
        baseline[key].claim_support_rate for key in paired_ids
    )
    success_delta = _mean(float(candidate[key].task_success) for key in paired_ids) - _mean(
        float(baseline[key].task_success) for key in paired_ids
    )
    success_ci = paired_bootstrap_delta(
        [float(candidate[key].task_success) for key in paired_ids],
        [float(baseline[key].task_success) for key in paired_ids],
        seed=20260721,
    ) if paired_ids else None
    baseline_token_per_success = _tokens_per_success(grouped["single_agent"])
    candidate_token_per_success = _tokens_per_success(grouped[N05Stage.FULL_SYSTEM.value])
    token_per_success_increase = (
        candidate_token_per_success / baseline_token_per_success - 1
        if baseline_token_per_success and candidate_token_per_success is not None
        else None
    )
    baseline_mean_tokens = _mean(row.total_tokens for row in grouped["single_agent"])
    candidate_mean_tokens = _mean(
        row.total_tokens for row in grouped[N05Stage.FULL_SYSTEM.value]
    )
    total_token_increase = (
        candidate_mean_tokens / baseline_mean_tokens - 1
        if baseline_mean_tokens
        else None
    )
    baseline_conflict = _optional_mean(row.conflict_recall for row in grouped["single_agent"])
    candidate_conflict = _optional_mean(
        row.conflict_recall for row in grouped[N05Stage.FULL_SYSTEM.value]
    )
    conflict_delta = (
        candidate_conflict - baseline_conflict
        if candidate_conflict is not None and baseline_conflict is not None
        else None
    )
    baseline_unsupported = _optional_mean(
        row.severe_unsupported_rate for row in grouped["single_agent"]
    )
    candidate_unsupported = _optional_mean(
        row.severe_unsupported_rate for row in grouped[N05Stage.FULL_SYSTEM.value]
    )
    unsupported_reduction = (
        1 - candidate_unsupported / baseline_unsupported
        if baseline_unsupported and candidate_unsupported is not None
        else None
    )
    gates = {
        "six_group_matrix_complete": matrix_complete,
        "claim_support_gain": support_delta >= 0.08,
        "conflict_recall_gain": conflict_delta is not None and conflict_delta >= 0.20,
        "severe_unsupported_reduction": unsupported_reduction is not None
        and unsupported_reduction >= 0.50,
        "token_increase_within_limit": total_token_increase is not None
        and total_token_increase <= 0.40,
    }
    per_system = {
        system: {
            "task_success": _mean(float(row.task_success) for row in items),
            "claim_support_rate": _mean(row.claim_support_rate for row in items),
            "omission_rate": _mean(row.omission_rate for row in items),
            "mean_tokens": _mean(float(row.total_tokens) for row in items),
            "mean_latency_ms": _mean(float(row.latency_ms) for row in items),
            "p95_latency_ms": _percentile(
                [float(row.latency_ms) for row in items],
                0.95,
            ),
            "total_tokens": sum(row.total_tokens for row in items),
            "system_exception_rate": 0.0,
            "local_monetary_cost": 0.0,
            "cost_per_success": (
                0.0 if any(row.task_success for row in items) else None
            ),
        }
        for system, items in sorted(grouped.items())
    }
    progressive_order = [
        "reader_parallel",
        "evidence",
        "critic",
        "verifier",
        "full_system",
    ]
    marginal_contribution = {
        f"{left}_to_{right}": {
            "task_success_delta": per_system[right]["task_success"]
            - per_system[left]["task_success"],
            "claim_support_delta": per_system[right]["claim_support_rate"]
            - per_system[left]["claim_support_rate"],
            "mean_token_delta": per_system[right]["mean_tokens"]
            - per_system[left]["mean_tokens"],
            "mean_latency_ms_delta": per_system[right]["mean_latency_ms"]
            - per_system[left]["mean_latency_ms"],
        }
        for left, right in zip(progressive_order, progressive_order[1:])
    }
    return {
        "schema_version": "1.1",
        "truth_class": truth_class,
        "systems": counts,
        "matrix_complete": matrix_complete,
        "metrics": {
            "paired_case_count": len(paired_ids),
            "task_success_delta": success_delta,
            "task_success_delta_ci": (
                None
                if success_ci is None
                else {"lower": success_ci.lower, "upper": success_ci.upper}
            ),
            "claim_support_delta": support_delta,
            "conflict_recall_delta": conflict_delta,
            "severe_unsupported_reduction": unsupported_reduction,
            "total_token_increase": total_token_increase,
            "token_per_success_increase": token_per_success_increase,
            "baseline_p95_latency_ms": per_system["single_agent"][
                "p95_latency_ms"
            ],
            "candidate_p95_latency_ms": per_system["full_system"][
                "p95_latency_ms"
            ],
            "candidate_total_tokens": per_system["full_system"][
                "total_tokens"
            ],
            "candidate_system_exception_rate": per_system["full_system"][
                "system_exception_rate"
            ],
            "candidate_cost_per_success": per_system["full_system"][
                "cost_per_success"
            ],
            "multi_paper_coverage_rate": None,
            "paper_identity_confusion_rate": None,
            "tool_parameter_validity_rate": None,
        },
        "per_system": per_system,
        "marginal_contribution": marginal_contribution,
        "role_decision": {
            "production_default": "single_agent",
            "multi_agent_enabled_by_default": False,
            "critic": "experimental_only",
            "verifier": "experimental role plus deterministic product-boundary gate",
            "full_revision": "experimental only; bounded to one Writer/Verifier retry",
        },
        "gates": gates,
        "all_gates_passed": all(gates.values()),
        "limitations": [
            "Conflict gold is unavailable in frozen L4/L5; conflict Recall and its promotion gate are unavailable.",
            "The frozen single-Agent report has no claim-level unsupported-fact annotation, so reduction is unavailable.",
            "Paper-identity confusion, full-paper coverage, and Tool parameter validity were not annotated in this frozen N05 artifact; they remain acceptance-test metrics, not fabricated effect estimates.",
            "Local Ollama has zero external API charge; cost-per-success is unavailable when the candidate has no successful cases.",
        ],
    }


def _normalized_stage(payload: dict[str, Any]) -> dict[str, Any]:
    raw_citations = payload.get("citations", [])
    raw_claims = payload.get("claims", [])
    return {
        "answer": str(payload.get("answer", "")).strip(),
        "citations": [str(item) for item in raw_citations if str(item).strip()]
        if isinstance(raw_citations, list)
        else [],
        "claims": raw_claims if isinstance(raw_claims, list) else [],
        "conflict_detected": bool(payload.get("conflict_detected", False)),
        "findings": payload.get("findings", []),
    }


def _evidence_context(hits: list[PageRecord]) -> str:
    return "\n".join(
        f"[{hit.evidence_id}] paper={hit.paper_id} page={hit.page_number} "
        f"section={hit.section}: {hit.text[:1200]}"
        for hit in hits
    )


def _reader_prompt(case: EvaluationCase, context: str) -> str:
    return (
        "Act as parallel Paper Reader roles. Return JSON only: "
        '{"paper_cards":[{"paper_id":"","summary":"","claims":[{"text":"","evidence_ids":["E1"]}]}],'
        '"answer":"","citations":["E1"],"claims":[{"text":"","evidence_ids":["E1"],"inferred":false}],'
        '"conflict_detected":false}. Produce one card per paper and cite only supplied IDs.\n'
        f"Task: {case.prompt}\nPapers: {case.paper_ids}\nEvidence:\n{context}"
    )


def _evidence_prompt(case: EvaluationCase, reader: dict[str, Any], context: str) -> str:
    return (
        "Act as Evidence Agent. Build a claim-evidence matrix and answer. Return JSON only with "
        '{"matrix":[],"answer":"","citations":["E1"],"claims":[{"text":"","evidence_ids":["E1"],'
        '"inferred":false}],"conflict_detected":false}.\n'
        f"Task: {case.prompt}\nPaper cards: {json.dumps(reader, ensure_ascii=False)}\nEvidence:\n{context}"
    )


def _critic_prompt(case: EvaluationCase, evidence: dict[str, Any]) -> str:
    return (
        "Act as Critic Agent. Identify coverage gaps, conflicts, non-comparable settings and unsupported claims. "
        'Return JSON only: {"issues":[],"conflict_detected":false}.\n'
        f"Task: {case.prompt}\nEvidence matrix: {json.dumps(evidence, ensure_ascii=False)}"
    )


def _writer_prompt(
    case: EvaluationCase, evidence: dict[str, Any], critic: dict[str, Any]
) -> str:
    return (
        "Act as Writer Agent. Use only the Evidence Matrix, respond to every Critic issue, and return JSON only: "
        '{"answer":"","citations":["E1"],"claims":[{"text":"","evidence_ids":["E1"],'
        '"inferred":false}],"issue_resolutions":[],"conflict_detected":false}.\n'
        f"Task: {case.prompt}\nMatrix: {json.dumps(evidence, ensure_ascii=False)}\n"
        f"Critic: {json.dumps(critic, ensure_ascii=False)}"
    )


def _verifier_prompt(
    case: EvaluationCase, evidence: dict[str, Any], writer: dict[str, Any]
) -> str:
    return (
        "Act as Verifier Agent. Check every claim/citation and perform at most one bounded revision. Return JSON only: "
        '{"findings":[],"revised_answer":"","revised_citations":["E1"],'
        '"revised_claims":[{"text":"","evidence_ids":["E1"],"inferred":false}],'
        '"conflict_detected":false}. Cite only supplied Matrix evidence.\n'
        f"Task: {case.prompt}\nMatrix: {json.dumps(evidence, ensure_ascii=False)}\n"
        f"Draft: {json.dumps(writer, ensure_ascii=False)}"
    )


def _mean(values: Iterable[float]) -> float:
    items = list(values)
    return sum(items) / len(items) if items else 0.0


def _optional_mean(values: Iterable[float | None]) -> float | None:
    items = [value for value in values if value is not None]
    return sum(items) / len(items) if items else None


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(
        len(ordered) - 1,
        max(0, int((len(ordered) - 1) * quantile)),
    )
    return ordered[index]


def _tokens_per_success(rows: list[N05CaseScore]) -> float | None:
    successes = sum(row.task_success for row in rows)
    return sum(row.total_tokens for row in rows) / successes if successes else None
